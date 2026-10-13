# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project
  region  = var.region
  zone    = var.zone
}

locals {
  devices = {
    server   = var.server_machine_type
    client   = var.client_machine_type
    backends = var.backends_machine_type
  }
}

resource "google_compute_network" "perf" {
  name                    = "provisa-perf"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "perf" {
  name          = "provisa-perf"
  region        = var.region
  network       = google_compute_network.perf.id
  ip_cidr_range = var.subnet_cidr
}

# The three devices reach each other on any port; nothing else does.
resource "google_compute_firewall" "between_devices" {
  name    = "provisa-perf-between-devices"
  network = google_compute_network.perf.name
  allow {
    protocol = "all"
  }
  source_tags = ["provisa-perf"]
  target_tags = ["provisa-perf"]
}

# The operator's SSH, from the addresses given.
resource "google_compute_firewall" "operator_ssh" {
  name    = "provisa-perf-operator-ssh"
  network = google_compute_network.perf.name
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  source_ranges = var.operator_ssh_cidrs
  target_tags   = ["provisa-perf"]
}

# The devices are placed close together, so the round trip between them is short and the same
# from one run to the next.
resource "google_compute_resource_policy" "compact" {
  name   = "provisa-perf-compact"
  region = var.region
  group_placement_policy {
    collocation = "COLLOCATED"
  }
}

resource "google_compute_instance" "device" {
  for_each     = local.devices
  name         = "provisa-perf-${each.key}"
  machine_type = each.value
  zone         = var.zone
  tags         = ["provisa-perf"]
  labels = {
    provisa-perf-device = each.key
  }

  boot_disk {
    initialize_params {
      image = var.image
      size  = var.disk_gb
      type  = var.disk_type
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.perf.id
    nic_type   = "GVNIC"
    # An external address for the operator's SSH only; the firewall admits nothing else.
    access_config {}
  }

  resource_policies = [google_compute_resource_policy.compact.id]

  scheduling {
    # A compact placement policy needs instances that stop for host maintenance.
    on_host_maintenance = "TERMINATE"
    automatic_restart   = false
    provisioning_model  = var.provisioning_model
    preemptible         = var.provisioning_model == "SPOT"
    # A reclaimed Spot device stops (its disk and seeded data kept), as an idle one powers off.
    instance_termination_action = var.provisioning_model == "SPOT" ? "STOP" : null
  }

  # Run at every boot: Docker, the repository at var.commit, uv sync, the idle shutdown, and on
  # the backends device the data stack and its first seed (startup.sh.tftpl).
  metadata = {
    startup-script = templatefile("${path.module}/startup.sh.tftpl", {
      device   = each.key
      commit   = var.commit
      repo_url = var.repo_url
      repo_dir = var.repo_dir
    })
  }
}
