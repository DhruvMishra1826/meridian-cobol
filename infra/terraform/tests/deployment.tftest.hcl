mock_provider "docker" {}

variables {
  api_token = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}

run "secure_local_deployment" {
  command = plan
  assert {
    condition     = docker_container.meridian.read_only && docker_container.meridian.user == "10001:10001"
    error_message = "The application must have a read-only root filesystem and an unprivileged user."
  }
  assert {
    condition     = one(docker_container.meridian.capabilities).drop == toset(["ALL"])
    error_message = "Every Linux capability must be dropped."
  }
  assert {
    condition     = one(docker_container.meridian.ports).ip == "127.0.0.1"
    error_message = "HTTP must bind only to loopback."
  }
  assert {
    condition     = docker_network.service.driver == "bridge" && !docker_network.service.internal && docker_container.meridian.remove_volumes == false
    error_message = "Use a dedicated bridge supporting loopback port publication and retain the persistent journal."
  }
  assert {
    condition     = contains(docker_container.meridian.security_opts, "no-new-privileges:true")
    error_message = "Privilege escalation must be blocked."
  }
  assert {
    condition     = docker_container.meridian.wait && docker_container.meridian.memory == 256
    error_message = "Apply must wait for readiness and enforce the declared memory ceiling."
  }
}

run "custom_instance" {
  command = plan
  variables {
    name      = "meridian-isolated"
    host_port = 19080
    memory_mb = 512
  }
  assert {
    condition     = docker_container.meridian.name == "meridian-isolated" && one(docker_container.meridian.ports).external == 19080
    error_message = "Custom deployment identity and port must be honored."
  }
  assert {
    condition     = docker_volume.journal.name == "meridian-isolated-journal"
    error_message = "Each instance needs its own persistent journal volume."
  }
  assert {
    condition     = output.console_url == "http://127.0.0.1:19080"
    error_message = "Published connection details must match the requested port."
  }
}

run "reject_short_token" {
  command = plan
  variables {
    api_token = "short"
  }
  expect_failures = [var.api_token]
}

run "reject_token_whitespace" {
  command = plan
  variables {
    api_token = "xxxxxxxxxxxxxxxx xxxxxxxxxxxxxxxxxxxxxxxx"
  }
  expect_failures = [var.api_token]
}

run "reject_network_daemon" {
  command = plan
  variables {
    docker_host = "tcp://127.0.0.1:2375"
  }
  expect_failures = [var.docker_host]
}

run "reject_unicode_token" {
  command = plan
  variables {
    api_token = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxé"
  }
  expect_failures = [var.api_token]
}

run "reject_relative_socket" {
  command = plan
  variables {
    docker_host = "unix://relative.sock"
  }
  expect_failures = [var.docker_host]
}

run "reject_privileged_port" {
  command = plan
  variables {
    host_port = 80
  }
  expect_failures = [var.host_port]
}

run "reject_fractional_port" {
  command = plan
  variables {
    host_port = 8080.5
  }
  expect_failures = [var.host_port]
}

run "reject_invalid_name" {
  command = plan
  variables {
    name = "../Bad Name"
  }
  expect_failures = [var.name]
}

run "reject_unbounded_memory" {
  command = plan
  variables {
    memory_mb = 8192
  }
  expect_failures = [var.memory_mb]
}
