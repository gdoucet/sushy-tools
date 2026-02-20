# Copyright 2019 Red Hat, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
from sushy_tools import error

try:
    from proxmoxer import ProxmoxAPI
    from proxmoxer.tools.files import Files
    from proxmoxer.core import ResourceException

except ImportError:
    ProxmoxAPI = None
    Files = None
    ResourceException = None

class DriverBase(object):
    """Common base for emulated Redfish resource drivers"""

    def __init__(self, config, logger):
        """Initialize a driver.

        :params config: system configuration dict
        :params logger: system logger object
        """
        self._config = config
        self._logger = logger

class ProxmoxDriverBase(DriverBase):
    """Common base for emulated Redfish resource drivers"""

    def __init__(self, config, logger):
        super().__init__(config, logger)
        if not ProxmoxAPI:
            return
        host = config.get("SUSHY_EMULATOR_PROXMOX_HOST")
        user = config.get("SUSHY_EMULATOR_PROXMOX_USER")
        password = config.get("SUSHY_EMULATOR_PROXMOX_PASSWORD")
        token_name = config.get("SUSHY_EMULATOR_PROXMOX_TOKEN_NAME")
        token_value = config.get("SUSHY_EMULATOR_PROXMOX_TOKEN_VALUE")
        verify_ssl = config.get("SUSHY_EMULATOR_PROXMOX_VERIFY_SSL", True)
        timeout = config.get("SUSHY_EMULATOR_PROXMOX_TIMEOUT", 300)

        if token_name and token_value:
            # Use API token
            self._proxmox = ProxmoxAPI(
                host,
                user=user,
                token_name=token_name,
                token_value=token_value,
                verify_ssl=verify_ssl,
                timeout=timeout
            )
        else:
            # Use password
            self._proxmox = ProxmoxAPI(
                host, user=user, password=password, verify_ssl=verify_ssl, timeout=timeout
            )

    def _find_vm_resource(self, identity):
        """Find a VM by name or vmid."""
        for node in self._proxmox.nodes.get():
            for vm in self._proxmox.nodes(node["node"]).qemu.get():
                if str(vm["vmid"]) == identity:
                    return self._proxmox.nodes(node["node"]).qemu(vm["vmid"])

    def _get_vm_config(self, identity):
        vm = self._find_vm_resource(identity)
        if vm:
            return vm.config.get()

        msg = f'Error finding VM by name/vmid "{identity}"'
        self._logger.debug(msg)
        raise error.NotFound(msg)

    def _get_storage_collection(self, identity):
        """Get a dict of Simple Storage Controllers and their devices"""
        config = self._get_vm_config(identity)
        storage_col = {}
        for key, value in config.items():
            if key.startswith(("scsi", "ide", "sata", "virtio")):
                if key == "scsihw":
                    continue
                # e.g. scsi0: local-lvm:vm-100-disk-0,size=32G
                parts = value.split(",")
                disk_info = parts[0]
                if ":" not in disk_info:
                    continue
                storage, path = disk_info.split(":")
                size_bytes = 0
                for part in parts:
                    if "size=" in part:
                        size_str = part.split("=")[1]
                        if size_str.upper().endswith("G"):
                            size_bytes = int(float(size_str[:-1]) * 1024 * 1024 * 1024)
                        elif size_str.upper().endswith("M"):
                            size_bytes = int(float(size_str[:-1]) * 1024 * 1024)

                ctl_type = "".join(filter(str.isalpha, key))
                if ctl_type not in storage_col:
                    storage_col[ctl_type] = {
                        "Id": ctl_type,
                        "Name": ctl_type,
                        "DeviceList": [],
                    }
                storage_col[ctl_type]["DeviceList"].append(
                    {"Name": path, "CapacityBytes": size_bytes}
                )
        return storage_col
