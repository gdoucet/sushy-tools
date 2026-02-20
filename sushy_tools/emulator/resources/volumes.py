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

from logging import config
import uuid

from sushy_tools.emulator import memoize
from sushy_tools.emulator.resources import base


class StaticDriver(base.DriverBase):
    """Redfish Volumes emulated in libvirt backed by the config file

    Maintains the libvirt volumes in memory.
    """

    def __init__(self, config, logger):
        super().__init__(config, logger)
        self._volumes = memoize.PersistentDict()
        self._volumes.make_permanent(
            self._config.get('SUSHY_EMULATOR_STATE_DIR'), 'volumes')

        self._volumes.update(
            self._config.get('SUSHY_EMULATOR_VOLUMES', {}))

    @property
    def driver(self):
        """Return human-friendly driver information

        :returns: driver information as `str`
        """
        return '<static-volumes>'

    def get_volumes_col(self, identity, storage_id):
        try:
            uu_identity = str(uuid.UUID(identity))

            return self._volumes[(uu_identity, storage_id)]

        except (KeyError, ValueError):
            msg = ('Error finding volume collection by System UUID %s '
                   'and Storage ID %s' % (uu_identity, storage_id))
            self._logger.debug(msg)

    def add_volume(self, uu_identity, storage_id, vol):
        if not self._volumes[(uu_identity, storage_id)]:
            self._volumes[(uu_identity, storage_id)] = []

        vol_col = self._volumes[(uu_identity, storage_id)]
        vol_col.append(vol)
        self._volumes.update({(uu_identity, storage_id): vol_col})

    def delete_volume(self, uu_identity, storage_id, vol):
        try:
            vol_col = self._volumes[(uu_identity, storage_id)]
        except KeyError:
            msg = ('Error finding volume collection by System UUID %s '
                   'and Storage ID %s' % (uu_identity, storage_id))
            self._logger.debug(msg)
        else:
            vol_col.remove(vol)
            self._volumes.update({(uu_identity, storage_id): vol_col})


class ProxmoxDriver(base.ProxmoxDriverBase):
    """Redfish Volumes emulated in libvirt backed by the config file

    Maintains the libvirt volumes in memory.
    """

    def __init__(self, config, logger):
        super().__init__(config, logger)

    @property
    def driver(self):
        """Return human-friendly driver information

        :returns: driver information as `str`
        """
        return '<proxmox-volumes>'

    def get_volumes_col(self, identity, storage_id):
        config = self._get_vm_config(identity)
        volumes = []
        for key, value in config.items():
            if key == 'scsihw':
                continue
            if key.startswith("scsi"):
                values = value.split(",")
                drive_name = values[0]
                values = values[1:]
                properties = {value.split("=")[0]: value.split("=")[1] for value in values}
                capacity = properties.get('size', '0')
                if 'G' in capacity:
                    capacity = int(capacity.replace('G', '')) * 1024 * 1024 * 1024

                volumes.append({'Id': key, 'Name': drive_name, 'CapacityBytes': capacity, 'VolumeType': 'RawDevice'})

        return volumes
