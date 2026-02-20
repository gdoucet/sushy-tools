# Copyright 2024 Red Hat, Inc.
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

import math
from pyexpat import model

from sushy_tools.emulator import memoize
from sushy_tools.emulator.resources.systems.base import AbstractSystemsDriver
from sushy_tools import error

try:
    from proxmoxer import ProxmoxAPI
    from proxmoxer.tools.files import Files
    from proxmoxer.core import ResourceException

except ImportError:
    ProxmoxAPI = None
    Files = None
    ResourceException = None

is_loaded = bool(ProxmoxAPI)


class ProxmoxDriver(AbstractSystemsDriver):
    """Proxmox driver"""

    BOOT_DEVICE_MAP = {
        "Pxe": "net0",
        "Hdd": "scsi0",
        "Cd": "ide2",
    }

    BOOT_DEVICE_MAP_REV = {v: k for k, v in BOOT_DEVICE_MAP.items()}

    BOOT_MODE_MAP = {
        "Legacy": "seabios",
        "UEFI": "ovmf",
    }

    BOOT_MODE_MAP_REV = {v: k for k, v in BOOT_MODE_MAP.items()}

    DEFAULT_FIRMWARE_VERSIONS = {"BiosVersion": "1.0.0"}

    DEFAULT_BIOS_ATTRIBUTES = {"BootMode": "Uefi",
                               "EmbeddedSata": "Raid",
                               "L2Cache": "10x256 KB",
                               "NicBoot1": "NetworkBoot",
                               "NumCores": "10",
                               "QuietBoot": "true",
                               "ProcTurboMode": "Enabled",
                               "SecureBootStatus": "Enabled",
                               "SerialNumber": "QPX12345",
                               "SysPassword": ""}

    @classmethod
    def initialize(cls, config, logger, *args, **kwargs):
        cls._config = config
        cls._logger = logger

        if not hasattr(cls, "_bios"):
            cls._bios = {}
        if not hasattr(cls, "_firmware_versions"):
            cls._firmware_versions = {}
        if not hasattr(cls, "_proxmox"):
            host = config.get("SUSHY_EMULATOR_PROXMOX_HOST")
            user = config.get("SUSHY_EMULATOR_PROXMOX_USER")
            password = config.get("SUSHY_EMULATOR_PROXMOX_PASSWORD")
            token_name = config.get("SUSHY_EMULATOR_PROXMOX_TOKEN_NAME")
            token_value = config.get("SUSHY_EMULATOR_PROXMOX_TOKEN_VALUE")
            verify_ssl = config.get("SUSHY_EMULATOR_PROXMOX_VERIFY_SSL", True)
            timeout = config.get("SUSHY_EMULATOR_PROXMOX_TIMEOUT", 300)

            if token_name and token_value:
                # Use API token
                cls._proxmox = ProxmoxAPI(
                    host,
                    user=user,
                    token_name=token_name,
                    token_value=token_value,
                    verify_ssl=verify_ssl,
                    timeout=timeout
                )
            else:
                # Use password
                cls._proxmox = ProxmoxAPI(
                    host, user=user, password=password, verify_ssl=verify_ssl, timeout=timeout
                )

        cls._http_boot_uri = None
        cls._iso_storage = config.get("SUSHY_EMULATOR_PROXMOX_ISO_STORAGE", "local")


        return cls

    def _find_vm(self, identity):
        """Find a VM by name or vmid."""
        for node in self._proxmox.nodes.get():
            for vm in self._proxmox.nodes(node["node"]).qemu.get():
                if str(vm["vmid"]) == identity:
                    return vm
        return None

    def _find_vm_resource(self, identity):
        """Find a VM by name or vmid."""
        for node in self._proxmox.nodes.get():
            for vm in self._proxmox.nodes(node["node"]).qemu.get():
                if str(vm["vmid"]) == identity:
                    return self._proxmox.nodes(node["node"]).qemu(vm["vmid"])

    def _find_node_resource_by_vmid(self, identity):
        """Find a VM by name or vmid."""
        for node in self._proxmox.nodes.get():
            for vm in self._proxmox.nodes(node["node"]).qemu.get():
                if str(vm["vmid"]) == identity:
                    return node

    # @memoize.memoize()
    def _get_vm(self, identity):
        vm = self._find_vm(identity)
        if vm:
            return vm

        msg = f'Error finding VM by name/vmid "{identity}"'
        self._logger.debug(msg)
        raise error.NotFound(msg)

    # @memoize.memoize()
    def _get_vm_config(self, identity):
        vm = self._find_vm_resource(identity)
        if vm:
            return vm.config.get()

        msg = f'Error finding VM by name/vmid "{identity}"'
        self._logger.debug(msg)
        raise error.NotFound(msg)

    # @memoize.memoize()
    def _get_vm_resource(self, identity):
        vm = self._find_vm_resource(identity)
        if vm:
            return vm

        msg = f'Error finding VM by name/vmid "{identity}"'
        self._logger.debug(msg)
        raise error.NotFound(msg)

    @property
    def driver(self):
        """Return human-friendly driver description"""
        return "<Proxmox>"

    @property
    def systems(self):
        """Return available computer systems (VMs)"""
        systems = []
        for node in self._proxmox.nodes.get():
            for vm in self._proxmox.nodes(node["node"]).qemu.get():
                systems.append(str(vm["vmid"]))
        return systems

    def uuid(self, identity):
        """Get computer system UUID (vmid)"""
        vm = self._get_vm(identity)
        return str(vm["vmid"])

    def name(self, identity):
        """Get computer system name"""
        vm = self._get_vm(identity)
        return vm["name"]

    def get_power_state(self, identity):
        """Get computer system power state"""
        vm = self._get_vm(identity)

        self._logger.debug(f"VM status is {vm['status']}")
        return "On" if vm["status"] == "running" else "Off"

    def set_power_state(self, identity, state):
        """Set computer system power state"""
        vm = self._get_vm_resource(identity)
        current_status = vm.status.current.get()["status"]
        self._logger.debug(f"Current status is {current_status}")

        try:
            if state in ("On", "ForceOn"):
                if current_status != "running":
                    self._logger.debug(f"Powering on VM {identity}")
                    vm.status.start.post()
            elif state in ("ForceOff", "GracefulShutdown"):
                if current_status == "running":
                    if state == "GracefulShutdown":
                        self._logger.debug(f"Powering off VM {identity}")
                        vm.status.shutdown.post()
                    else:
                        self._logger.debug(f"Forcing power off VM {identity}")
                        vm.status.stop.post(**{"overrule-shutdown": 1})
            elif state in ("ForceRestart", "GracefulRestart"):
                if current_status == "running":
                    if state == "GracefulRestart":
                        self._logger.debug(f"Restarting VM {identity}")
                        vm.status.reboot.post()
                    else:
                        self._logger.debug(f"Forcing restart VM {identity}")
                        vm.status.reset.post()
            elif state == "Nmi":
                raise error.NotSupportedError("NMI is not supported")
            else:
                raise error.BadRequest(f'Unknown ResetType "{state}"')
        except ResourceException as e:
            # You can inspect the exception to provide better error messages
            if e.status_code == 403:
                # This is a permission issue
                raise error.FishyError(f"Proxmox permission error: {e.content}")
            elif e.status_code == 404:
                # The resource might have been deleted between calls
                raise error.NotFound(f"VM '{identity}' not found during power operation: {e.content}")
            else:
                # For other API errors (like 500, 400)
                raise error.FishyError(f"Proxmox API error (status {e.status_code}): {e.content}")
        except Exception as e:
            # Catch other unexpected errors
            raise error.FishyError(f"An unexpected error occurred: {e}")

    def get_boot_device(self, identity):
        """Get computer system boot device name"""
        config = self._get_vm_config(identity)
        boot_order = config.get("boot", "")
        # boot order is a string like "order=scsi0;ide2;net0"
        if boot_order:
            first_device = boot_order.split(";")[0]
            # handle "order=scsi0" format
            if "=" in first_device:
                first_device = first_device.split("=")[1]
            self._logger.debug(f"Boot device is {first_device}")
            return self.BOOT_DEVICE_MAP_REV.get(first_device)
        self._logger.debug("Boot device is Hdd")
        return "Hdd"  # Default

    def set_boot_device(self, identity, boot_source):
        """Set computer system boot device name"""
        try:
            target = self.BOOT_DEVICE_MAP[boot_source]
        except KeyError:
            raise error.BadRequest(f"Unknown boot source: {boot_source}")

        config = self._get_vm_config(identity)
        vm = self._get_vm_resource(identity)
        current_boot_order = config.get("boot", "order=scsi0;ide2;net0")
        devices = current_boot_order.split("=")[1].split(";")

        # Move target to the front
        if target in devices:
            devices.remove(target)
        devices.insert(0, target)

        new_boot_order = f"order={';'.join(devices)}"
        self._logger.debug(f"Setting boot order to {new_boot_order}")
        vm.config.set(boot=new_boot_order)

    def get_boot_mode(self, identity):
        """Get computer system boot mode."""
        config = self._get_vm_config(identity)
        bios = config.get("bios", "seabios")
        self._logger.debug(f"Boot mode is {self.BOOT_MODE_MAP_REV.get(bios)}")
        return self.BOOT_MODE_MAP_REV.get(bios)

    def set_boot_mode(self, identity, boot_mode):
        """Set computer system boot mode."""
        vm = self._get_vm_resource(identity)
        try:
            target_bios = self.BOOT_MODE_MAP[boot_mode]
        except KeyError:
            raise error.BadRequest(f"Unknown boot mode: {boot_mode}")

        if self.get_power_state(identity) == "On":
            raise error.FishyError("Cannot change boot mode while VM is running.")

        current_config = self._get_vm_config(identity)
        if current_config.get("bios") == target_bios:
            self._logger.debug(f"Boot mode is already {boot_mode}")
            return

        if boot_mode == "UEFI":
            # Find a storage for EFI disk
            storages = self._proxmox.storage.get()
            efi_storage = None
            for s in storages:
                if "images" in s["content"].split(","):
                    efi_storage = s["storage"]
                    break
            if not efi_storage:
                raise error.FishyError("No storage found for EFI disk")
            self._logger.debug(f"Using storage {efi_storage} for EFI disk")
            self._logger.debug(f"Setting boot mode to {target_bios}")
            vm.config.set(bios=target_bios, efidisk0=f"{efi_storage}:1")
        else:  # Legacy
            self._logger.debug(f"Setting boot mode to {target_bios}")
            vm.config.set(bios=target_bios)
            # Proxmoxer doesn't have a simple way to delete a key
            # We need to form a post request to delete it.
            # This is a bit of a hack.
            vm.config.post(delete="efidisk0")

    def get_secure_boot(self, identity):
        """Get computer system secure boot state for UEFI boot mode."""
        config = self._get_vm_config(identity)
        if config.get("bios") != "ovmf":
            raise error.NotSupportedError("Secure Boot is only available in UEFI mode.")

        # Proxmox secure boot is part of the efidisk setting
        efidisk = config.get("efidisk0")
        if efidisk and "secureboot=1" in efidisk:
            self._logger.debug("Secure Boot is enabled")
            return True

        self._logger.debug("Secure Boot is disabled")
        return False

    def set_secure_boot(self, identity, secure):
        """Set computer system secure boot state for UEFI boot mode."""
        config = self._get_vm_config(identity)
        vm = self._get_vm_resource(identity)
        if config.get("bios") != "ovmf":
            raise error.NotSupportedError("Secure Boot is only available in UEFI mode.")

        if self.get_power_state(identity) == "On":
            raise error.FishyError("Cannot change secure boot while VM is running.")

        efidisk = config.get("efidisk0")
        if not efidisk:
            raise error.FishyError("EFI disk not configured. Cannot set Secure Boot.")

        # efidisk0 format: <storage>:1,efitype=4m,pre-enrolled-keys=1,secureboot=1
        parts = efidisk.split(",")
        storage_part = parts[0]
        options = {p.split("=")[0]: p.split("=")[1] for p in parts[1:] if "=" in p}

        if secure:
            options["secureboot"] = "1"
            options["pre-enrolled-keys"] = "1"
        else:
            options.pop("secureboot", None)

        new_options = [f"{k}={v}" for k, v in options.items()]
        new_efidisk = ",".join([storage_part] + new_options)

        self._logger.debug(f"Setting secure boot to {secure}")
        vm.config.set(efidisk0=new_efidisk)

    def get_total_memory(self, identity):
        """Get computer system total memory"""
        config = self._get_vm_config(identity)
        # memory is in MB
        memory_mb = int(config.get("memory", 0))
        return int(math.ceil(memory_mb / 1024))

    def get_total_cpus(self, identity):
        """Get computer system total count of available CPUs"""
        config = self._get_vm_config(identity)
        return config.get("cores", 1) * config.get("sockets", 1)

    def get_nics(self, identity):
        """Get list of NICs and their attributes"""
        config = self._get_vm_config(identity)
        nics = []
        for key, value in config.items():
            if key.startswith("net"):
                # format is virtio=... or e1000=...
                mac = value.split("=")[1].split(",")[0]
                nics.append({"id": mac, "mac": mac})
        return nics

    def get_boot_image(self, identity, device):
        """Get backend VM boot image info"""
        if device != "Cd":
            raise error.NotSupportedError(
                f"Getting boot image for {device} is not supported."
            )
        config = self._get_vm_config(identity)
        cdrom_path = config.get("ide2")
        if cdrom_path:
            # format: <storage>:<path>,media=cdrom
            image_name = cdrom_path.split(",")[0]
            inserted = self.get_boot_device(identity) == "Cd"
            return image_name, True, inserted

        return None, True, False

    def set_boot_image(self, identity, device, boot_image=None, write_protected=True):
        """Set backend VM boot image"""
        storage_name = self._iso_storage

        if device != "Cd":
            raise error.NotSupportedError(
                f"Setting boot image for {device} is not supported."
            )

        vm = self._get_vm_resource(identity)
        node = self._find_node_resource_by_vmid(identity)
        node_name = node["node"]

        if boot_image:
            file_name = boot_image.split("/")[-1]
            proxmox_file = Files(self._proxmox, node_name, storage_name)
            proxmox_file.upload_local_file_to_storage(filename=boot_image, blocking_status=True)
            # boot_image is expected to be in format <storage>:<path>
            # e.g. 'local:iso/ubuntu.iso'
            vm.config.set(ide2=f"{storage_name}:iso/{file_name},media=cdrom")
        else:
            # Eject
            vm.config.set(ide2="none,media=cdrom")

    def get_http_boot_uri(self, identity):
        """Return the URI stored for the HttpBootUri.

        :param identity: The libvirt identity. Unused, exists for internal
                         sushy-tools compatibility.
        :returns: Stored URI value for HttpBootURI.
        """
        return self._http_boot_uri

    def set_http_boot_uri(self, uri):
        """Stores the Uri for HttpBootURI.

        :param uri: String to return

        :returns: None
        """
        self._http_boot_uri = uri

    # The following methods are not implemented for Proxmox as they
    # require more complex interactions or are not directly supported.
    # They will raise NotSupportedError from the base class.

    def get_bios(self, identity):
        """Get BIOS attributes for the system"""
        if identity not in self._bios:
            return self.DEFAULT_BIOS_ATTRIBUTES
        return self._bios[identity]


    def set_bios(self, identity, attributes):
        """Update BIOS attributes"""
        bios = self.get_bios(identity)
        bios.update(attributes)
        self._bios[identity] = bios
        

    def reset_bios(self, identity):
        """Reset BIOS attributes to default"""
        if identity in self._bios:
            del self._bios[identity]

    def get_versions(self, identity):
        """Get firmware version information for the system"""
        if identity in self._firmware_versions:
            return self._firmware_versions[identity]
        return self.DEFAULT_FIRMWARE_VERSIONS

    def set_versions(self, identity, firmware_versions):
        """Update firmware versions"""
        self._firmware_versions[identity] = firmware_versions

    def reset_versions(self, identity):
        """Reset firmware versions to default"""
        if identity in self._firmware_versions:
            del self._firmware_versions[identity]

    def get_simple_storage_collection(self, identity):
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

    def find_or_create_storage_volume(self, data):
        """Find/create volume based on existence in the virtualization backend"""
        return data['Id']

    def get_processors(self, identity):
        """Get processor information for the system"""
        config = self._get_vm_config(identity)
        cores_count = config.get("cores", 1)
        sockets_count = config.get("sockets", 1)
        processors = [{'id': 'CPU{0}'.format(x),
                'socket': 'CPU {0}'.format(x)}
                for x in range(sockets_count)]
        model = config.get("cpu", "Unknown")
        vendor = 'KVM'
        for processor in processors:
            processor['model'] = model
            processor['vendor'] = vendor
            processor['cores'] = cores_count
            processor['threads'] = '1'
        return processors
