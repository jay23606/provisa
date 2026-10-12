# Microsoft log fixtures

The text fixtures are the forms Microsoft's documentation gives for each log, with hosts and
users made up.

`windows_system.evtx` is the first 69,632 bytes (the file header and its first 64 KiB chunk, 153
records) of `tests/data/system.evtx` from python-evtx
(https://github.com/williballenthin/python-evtx, Apache License 2.0). python-evtx took that file
from plaso's test data (log2timeline/plaso, commit 1e2fa282, Apache License 2.0). The full file's
MD5 is 182de19fe6a25b928a34ad59af0bbf1e. Its records name only the test lab's machine
(WKS-WIN764BITB.shieldbase.local) and well-known system accounts (S-1-5-18, -19, -20): no
person's name or account.
