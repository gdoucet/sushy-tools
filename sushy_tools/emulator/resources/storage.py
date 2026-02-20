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

import uuid

from sushy_tools.emulator.resources import base
from sushy_tools import error

try:
    from proxmoxer import ProxmoxAPI
    from proxmoxer.tools.files import Files
    from proxmoxer.core import ResourceException

except ImportError:
    ProxmoxAPI = None
    Files = None
    ResourceException = None

class StaticDriver(base.DriverBase):
    """Redfish storage backed by configuration file"""

    def __init__(self, config, logger):
        super().__init__(config, logger)

    @property
    def driver(self):
        """Return human-friendly driver information

        :returns: driver information as `str`
        """
        return '<static-storage>'

    def get_storage_col(self, identity):
        try:
            uu_identity = str(uuid.UUID(identity))

            return self._storage[uu_identity]

        except KeyError:
            msg = ('Error finding storage collection by UUID '
                   '"%(identity)s"' % {'identity': identity})

            self._logger.debug(msg)

            raise error.FishyError(msg)

    def get_all_storage(self):
        """Returns all storage instances represented as tuples in the format:

        (System_ID, Storage_ID)

        :returns: list of tuples representing the storage instances
        """
        return [(k, st["Id"]) for k in self._storage
                for st in self._storage[k]]

class ProxmoxDriver(base.ProxmoxDriverBase):
    """Redfish storage for Proxmox"""

    def __init__(self, config, logger):
        super().__init__(config, logger)

    @property
    def driver(self):
        """Return human-friendly driver information

        :returns: driver information as `str`
        """
        return '<proxmox-storage>'



    def get_storage_col(self, identity):
        storages = self._get_storage_collection(identity)
        storage_col = []
        for storage in storages:
            drives = [device['Name'] for device in storages[storage]['DeviceList']]
            storage_col.append({'Id': storages[storage]['Id'], 'Name': storages[storage]['Name'], 'Drives': sorted(drives)})
        return storage_col
