# Copyright (c) 2026 Kenneth Stott
# Canary: 548a51a1-b128-4c56-91f2-f54d32ee6e13
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""A named demo's bundle: built once, published to a registry, pulled by whoever runs the demo
(REQ-2049).

A bundle is one demo, as its build left it: the demo's directory (config.yaml, demo.yaml, its tour
and example queries), what its seeder wrote (logs/), its data stores' dumps (dump/) and the seed
the sandbox tier lands its template from (seeded/). It is published as an OCI artifact in the one
repository every demo shares -- ``<registry>/provisa-demos``, so its visibility is set once --
tagged ``<name>-<version>`` and ``<name>-latest``. A version is never published twice.

The artifact's config blob is the bundle's manifest (``BundleManifest``): the demo, the version,
the commit it was built from and the oldest Provisa that runs it. Its one layer is the bundle, a
gzipped tar. A bundle that needs a newer Provisa than the one pulling it is refused by name before
its layer is fetched.

Only the OCI distribution API is spoken, over httpx, so neither a deployment nor a solution
engineer's machine needs a registry client installed. A registry that answers 401 names the token
service to ask (``WWW-Authenticate: Bearer``); an anonymous token pulls a public repository, and a
push passes the publisher's credentials to that service.
"""

# Requirements: REQ-2049

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

ARTIFACT_TYPE = "application/vnd.provisa.demo-bundle.v1"
CONFIG_TYPE = "application/vnd.provisa.demo-bundle.manifest.v1+json"
LAYER_TYPE = "application/vnd.provisa.demo-bundle.layer.v1.tar+gzip"
MANIFEST_TYPE = "application/vnd.oci.image.manifest.v1+json"
LATEST = "latest"
MANIFEST_FILE = "bundle.json"

# What a bundle leaves out of its demo's directory: the seeder's own marker volume.
_LEFT_OUT = ("data",)
# A version tag: the build's UTC minute and commit (202610141530-1a2b3c4d5).
_VERSION = re.compile(r"^\d{12}-[0-9a-f]{7,40}$")
# The release versions Provisa is published under (0.1.0, 0.1.0a483, 0.1.0rc1).
_PROVISA_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?$")
_PRE_RANK = {"a": 0, "b": 1, "rc": 2}


class BundleError(Exception):
    """A bundle could not be published or pulled; the message names why."""


class NeedsNewerProvisa(BundleError):
    """The bundle needs a newer Provisa than the one pulling it."""

    def __init__(self, manifest: BundleManifest, running: str) -> None:
        super().__init__(
            f"demo {manifest.demo} {manifest.version} needs Provisa {manifest.requires_provisa} "
            f"or newer; this is Provisa {running}"
        )
        self.manifest = manifest
        self.running = running


@dataclass(frozen=True)
class BundleManifest:
    demo: str
    version: str
    commit: str
    requires_provisa: str

    @classmethod
    def read(cls, data: dict) -> BundleManifest:
        missing = [f for f in ("demo", "version", "commit", "requires_provisa") if f not in data]
        if missing:
            raise BundleError(f"the bundle manifest has no {', '.join(missing)}")
        return cls(data["demo"], data["version"], data["commit"], data["requires_provisa"])


def provisa_version_key(version: str) -> tuple[int, int, int, int, int]:
    """``version`` ordered as PEP 440 orders a release and its pre-releases."""
    match = _PROVISA_VERSION.match(version)
    if match is None:
        raise BundleError(f"{version!r} is not a Provisa release version")
    major, minor, patch, pre, number = match.groups()
    stage, step = (_PRE_RANK[pre], int(number)) if pre else (3, 0)
    return (int(major), int(minor), int(patch), stage, step)


def running_provisa() -> str:
    from importlib.metadata import version

    return version("provisa")


def check_runs_here(manifest: BundleManifest, running: str) -> None:
    """Refuse, by name, a bundle that needs a newer Provisa than ``running``."""
    if provisa_version_key(running) < provisa_version_key(manifest.requires_provisa):
        raise NeedsNewerProvisa(manifest, running)


#: Where the project publishes its demos (demo-bundles.yml): what ``start-ui-install.sh --demo``
#: and a deployment's sandbox tier pull from unless told another registry (a test's own).
PUBLISHED_AT = "https://ghcr.io/kenstott"
#: The one repository every demo's bundles are published to.
REPOSITORY = "provisa-demos"


def tag_of(name: str, version: str) -> str:
    """The tag demo ``name``'s bundle ``version`` (or ``latest``) is published under."""
    return f"{name}-{version}"


# -- packing ------------------------------------------------------------------------------------


def pack(directory: Path, manifest: BundleManifest) -> bytes:
    """The bundle of ``directory`` (a built demo), as a gzipped tar, with ``manifest`` in it.
    Byte-for-byte the same for the same files: names sorted, times and owners cleared."""
    if not _VERSION.match(manifest.version):
        raise BundleError(f"{manifest.version!r} is not a bundle version (<UTC minute>-<commit>)")
    files = sorted(
        p
        for p in directory.rglob("*")
        if p.is_file() and p.relative_to(directory).parts[0] not in _LEFT_OUT
    )
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in files:
            _add(tar, str(path.relative_to(directory)), path.read_bytes(), path.stat().st_mode)
        _add(tar, MANIFEST_FILE, _manifest_bytes(manifest), 0o644)
    return gzip.compress(raw.getvalue(), mtime=0)


def _add(tar: tarfile.TarFile, name: str, data: bytes, mode: int) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode & 0o755
    tar.addfile(info, io.BytesIO(data))


def _manifest_bytes(manifest: BundleManifest) -> bytes:
    return json.dumps(asdict(manifest), indent=2, sort_keys=True).encode() + b"\n"


def unpack(blob: bytes, target: Path) -> None:
    """Write the bundle ``blob`` into ``target``, which must not exist. A member that is not a
    plain file or directory, or whose path leaves ``target``, refuses the whole bundle."""
    if target.exists():
        raise BundleError(f"{target} exists; a bundle is unpacked into a new directory")
    staging = target.with_name(f".{target.name}.unpacking")
    if staging.exists():
        raise BundleError(f"{staging} exists: an earlier unpack was interrupted; remove it")
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(blob)), mode="r") as tar:
        members = tar.getmembers()
        for member in members:
            if not (member.isfile() or member.isdir()):
                raise BundleError(f"the bundle holds {member.name!r}, which is not a file")
        tar.extractall(staging, members=members, filter="data")
    staging.rename(target)


# -- the registry -------------------------------------------------------------------------------


class Registry:
    """One registry namespace, e.g. ``https://ghcr.io/kenstott``. ``credentials`` (user, token)
    are passed to its token service when pushing."""

    def __init__(
        self,
        base: str,
        credentials: tuple[str, str] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        match = re.match(r"^(https?://[^/]+)/([a-z0-9._/-]+)$", base.rstrip("/"))
        if match is None:
            raise BundleError(f"{base!r} is not a registry namespace (https://host/namespace)")
        self.origin, self.namespace = match.groups()
        self.credentials = credentials
        self.client = client or httpx.Client(timeout=120, follow_redirects=True)
        self._tokens: dict[str, str] = {}

    def _url(self, path: str) -> str:
        return f"{self.origin}/v2/{self.namespace}/{REPOSITORY}/{path}"

    def _request(self, method: str, url: str, scope: str, **kw) -> httpx.Response:
        headers = dict(kw.pop("headers", {}))
        if scope in self._tokens:
            headers["Authorization"] = f"Bearer {self._tokens[scope]}"
        response = self.client.request(method, url, headers=headers, **kw)
        if response.status_code != 401 or scope in self._tokens:
            return response
        self._tokens[scope] = self._token(response.headers.get("www-authenticate", ""), scope)
        headers["Authorization"] = f"Bearer {self._tokens[scope]}"
        return self.client.request(method, url, headers=headers, **kw)

    def _token(self, challenge: str, scope: str) -> str:
        fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        if not challenge.lower().startswith("bearer ") or "realm" not in fields:
            raise BundleError(
                f"{self.origin} asked for credentials it does not name: {challenge!r}"
            )
        params = {"scope": scope}
        if "service" in fields:
            params["service"] = fields["service"]
        auth = httpx.BasicAuth(*self.credentials) if self.credentials else None
        response = self.client.get(fields["realm"], params=params, auth=auth)
        _ok(response, f"a token for {scope}")
        body = response.json()
        return body.get("token") or body["access_token"]

    def _scope(self, actions: str) -> str:
        return f"repository:{self.namespace}/{REPOSITORY}:{actions}"

    # pulling

    def resolve(self, name: str, tag: str) -> tuple[str, dict]:
        """The digest and manifest ``tag`` of demo ``name`` names."""
        response = self._request(
            "GET",
            self._url(f"manifests/{tag_of(name, tag)}"),
            self._scope("pull"),
            headers={"Accept": MANIFEST_TYPE},
        )
        if response.status_code == 404:
            raise BundleError(
                f"demo {name} has no bundle {tag!r} at {self.origin}/{self.namespace}"
            )
        _ok(response, f"demo {name} bundle {tag}")
        manifest = response.json()
        if manifest.get("artifactType") != ARTIFACT_TYPE:
            raise BundleError(f"demo {name} {tag} is not a demo bundle")
        return response.headers["docker-content-digest"], manifest

    def _blob(self, name: str, descriptor: dict) -> bytes:
        response = self._request(
            "GET", self._url(f"blobs/{descriptor['digest']}"), self._scope("pull")
        )
        _ok(response, f"demo {name} blob {descriptor['digest']}")
        if _digest(response.content) != descriptor["digest"]:
            raise BundleError(f"demo {name} blob {descriptor['digest']} does not match its digest")
        return response.content

    def manifest_of(self, name: str, oci_manifest: dict) -> BundleManifest:
        return BundleManifest.read(json.loads(self._blob(name, oci_manifest["config"])))

    def pull(self, name: str, tag: str, target: Path, running: str) -> BundleManifest:
        """Pull demo ``name``'s bundle ``tag`` into the new directory ``target``; refused before
        its layer is fetched when it needs a newer Provisa than ``running``."""
        _resolved, oci_manifest = self.resolve(name, tag)
        manifest = self.manifest_of(name, oci_manifest)
        if manifest.demo != name:
            raise BundleError(f"the bundle at {name} {tag} is demo {manifest.demo}'s")
        check_runs_here(manifest, running)
        (layer,) = oci_manifest["layers"]
        unpack(self._blob(name, layer), target)
        return manifest

    # pushing

    def exists(self, name: str, tag: str) -> bool:
        response = self._request(
            "HEAD",
            self._url(f"manifests/{tag_of(name, tag)}"),
            self._scope("pull"),
            headers={"Accept": MANIFEST_TYPE},
        )
        if response.status_code == 404:
            return False
        _ok(response, f"demo {name} bundle {tag}")
        return True

    def _put_blob(self, name: str, data: bytes) -> dict:
        digest = _digest(data)
        scope = self._scope("pull,push")
        started = self._request("POST", self._url("blobs/uploads/"), scope)
        _ok(started, f"an upload to demo {name}")
        location = httpx.URL(self.origin).join(started.headers["location"])
        done = self._request(
            "PUT",
            str(location.copy_merge_params({"digest": digest})),
            scope,
            content=data,
            headers={"Content-Type": "application/octet-stream"},
        )
        _ok(done, f"blob {digest} of demo {name}")
        return {"digest": digest, "size": len(data)}

    def push(self, manifest: BundleManifest, bundle: bytes) -> str:
        """Publish ``bundle`` as demo ``manifest.demo``'s version ``manifest.version`` and as its
        latest. A version already published is refused: a version names one bundle forever."""
        name = manifest.demo
        if self.exists(name, manifest.version):
            raise BundleError(f"demo {name} {manifest.version} is published already")
        config = {**self._put_blob(name, _manifest_bytes(manifest)), "mediaType": CONFIG_TYPE}
        layer = {
            **self._put_blob(name, bundle),
            "mediaType": LAYER_TYPE,
            "annotations": {"org.opencontainers.image.title": f"{name}-{manifest.version}.tar.gz"},
        }
        body = json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": MANIFEST_TYPE,
                "artifactType": ARTIFACT_TYPE,
                "config": config,
                "layers": [layer],
                "annotations": {
                    "org.opencontainers.image.version": manifest.version,
                    "org.opencontainers.image.revision": manifest.commit,
                },
            },
            sort_keys=True,
        ).encode()
        scope = self._scope("pull,push")
        for tag in (manifest.version, LATEST):
            put = self._request(
                "PUT",
                self._url(f"manifests/{tag_of(name, tag)}"),
                scope,
                content=body,
                headers={"Content-Type": MANIFEST_TYPE},
            )
            _ok(put, f"demo {name} tag {tag}")
        return _digest(body)


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _ok(response: httpx.Response, what: str) -> None:
    if response.status_code >= 300:
        raise BundleError(f"{what}: HTTP {response.status_code} {response.text[:300]}")
