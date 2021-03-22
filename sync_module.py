"""sync_module.py: Manages local and cloud game saves.

`Recursive hashing solution
<https://stackoverflow.com/questions/36204248/creating-unique-hash-for-directory-in-python>`_

----------------
COPYRIGHT NOTICE
----------------
Copyright (C) 2021 Samuel Wirth

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
import hashlib
# from datetime import datetime
import json
import os
import shutil
import tarfile
import time
import logging

from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive

start_time = time.time()


def hash_file(filepath):
    """Hash a single file, using sha1

    :param str filepath: Path to the file to be hashed.
    """

    hash_obj = hashlib.sha1()

    with open(filepath, 'rb') as f:
        while True:
            block = f.read(2 ** 10)
            if not block:
                break
            hash_obj.update(block)

        return hash_obj.hexdigest()


def hash_dir(path):
    """Recursively hash all files in a dir, and concatenate.
    
    :param path: The path to the dir to be hashed.
    """
    hashes = []

    for root, dirs, files in os.walk(path):
        for file in sorted(files):
            hashes.append(hash_file(os.path.join(root, file)))

        for d in sorted(dirs):
            hashes.append(hash_dir(os.path.join(root, d)))

        break

    hashes_concat = (''.join(hashes))
    final_hash = hashlib.sha1(hashes_concat.encode())
    return str(final_hash.hexdigest())


class SyncSession:
    """Integrate with google drive to upload and manage game saves.
    
    ----------------------
    Important definitions:  
    ----------------------
    - index: The index of a list, based on context.
    - local_index: The index of the game in the local config.
    - cloud_index: The index of the game in the cloud config.
    - remote: Google drive
    - save archive: An archive of a specific savegame, at a certain time.
    - base version: The origin save archive that the local save is based on.
    """

    def __init__(self):
        self.drive = None
        self.save_folder = None
        self.app_config = None
        with open('settings.json', 'r') as f:
            self.local_config = json.load(f)

    def update_local_config(self):
        """Update local config file to match changes"""

        with open('settings.json', 'w') as f:
            f.write(json.dumps(self.local_config, indent=4))

    def remote_config_handler(self, delete=False, index=None, **kwargs):
        """Read and write to the remote config['games']

        :param bool delete: When True, the selected index is deleted and the 'base_revision' is incremented
        :param int index: Optional. The index of the game item to return. Defaults to None, which returns all values.
        :param kwargs: Optional: Write values in config.
        :returns: Modified config. None if dict is inaccessible.
        :rtype: dict or None
        """

        try:
            working_json = json.loads(self.app_config.GetContentString())
        except AttributeError:
            return None

        if not delete:
            if index is not None:
                if kwargs:
                    working_json['games'][index].update(**kwargs)

                return_value = working_json['games'][index]
            else:
                if kwargs:
                    working_json['games'].append(kwargs)

                return_value = working_json['games']
        else:
            if kwargs:
                raise ValueError("Unexpected keyword arg(s) in deletion mode.")

            working_json['games'].pop(index)
            working_json.update(base_revision=working_json['base_revision'] + 1)
            return_value = working_json['games']

        if kwargs or delete:
            self.app_config.SetContentString(json.dumps(working_json, indent=4))
            self.app_config.Upload()

        return return_value

    def initialize_gdrive(self, original):
        """Initialize App in Google Drive; create app folder and config.

        :param original: Preexisting app folder if applicable.
        """

        self.save_folder = original or self.drive.CreateFile(
            {'title': 'Gamepass Saves', 'mimeType': 'application/vnd.google-apps.folder'}
        )
        self.save_folder.Upload()

        self.app_config = self.drive.CreateFile(
            {'title': 'config.json', 'mimeType': 'application/json', 'parents': [{'id': self.save_folder['id']}]}
        )
        self.app_config.SetContentString('{"base_revision": 0, "games": []}')
        self.app_config.Upload()

    def authenticate(self):
        """Create an authenticated drive session."""

        # The settings used allow app-only files to be changed, and credentials are saved
        gauth = GoogleAuth(settings_file='authentication/settings.yaml')
        gauth.LoadCredentialsFile()

        self.drive = GoogleDrive(gauth)

        folders = self.drive.ListFile(
            {"q": "'root' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"}
        ).GetList()

        for i in folders:
            if i['title'] == 'Gamepass Saves':
                self.save_folder = i
                break

        app_data = self.drive.ListFile(
            {"q": f"'{self.save_folder['id']}' in parents and mimeType='application/json' and trashed=false"}
        ).GetList()

        for i in app_data:
            if i['title'] == 'config.json':
                self.app_config = i
                break

        if self.app_config is None:
            self.initialize_gdrive(self.save_folder)

        print(self.save_folder['id'])
        print(self.app_config['id'])

    def diff(self, local_index, diff_local=True):
        """Determine whether the current save has changed locally or if it differs from the remote gamesave
        
        :param int local_index: The index of the game info in the local config
        :param bool diff_local: Check the base version against the current gamesave. Defaults to True.
        :returns: True if the saves are different.
        :rtype: bool
        """

        game_config = self.local_config['games'][local_index]
        base_hash = game_config['base_hash']

        if diff_local:
            current_hash = hash_dir(game_config['path'])

            if current_hash == base_hash:
                return False
            else:
                return True
        else:
            cloud_config = self.remote_config_handler(index=game_config['cloud_index'])
            cloud_hash = cloud_config['latest_hash']

            if cloud_hash == base_hash:
                return False
            else:
                return True

    def add_game_entry(self, name):
        self.remote_config_handler(name=name, saves=[], latest_hash='')

        save_root = self.drive.CreateFile(
            {
                'title': f"{name}_{len(self.remote_config_handler()) - 1}",
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [{'id': self.save_folder['id']}]
            }
        )
        save_root.Upload()

        self.remote_config_handler(index=-1, root_id=save_root['id'])

    def enable_game_entry(self, cloud_index, path):
        game_entry = self.remote_config_handler(index=cloud_index)
        local_entry = {'name': game_entry['name'], 'cloud_index': cloud_index, 'path': path, 'base_hash': ''}

        self.local_config['games'].append(local_entry)
        self.update_local_config()

    def push(self, local_index):
        """Upload saves as tarballs, keeping a history of saves

        :param local_index: The index of the game config in the local settings.
        """

        push_time = time.time()

        # Data we will be using
        local_config = self.local_config['games'][local_index]
        game_name = local_config['name']
        save_path = local_config['path']
        cloud_index = local_config['cloud_index']

        game_config = self.remote_config_handler(index=cloud_index)
        root_id = game_config['root_id']

        # Get the save's hash
        save_hash = hash_dir(save_path)
        self.remote_config_handler(index=cloud_index, latest_hash=save_hash)
        local_config.update(base_hash=save_hash)

        tar_time = time.time()
        print("tarring")

        archive_name = f'{game_name}_{cloud_index}-{time.time()}.save.tar'  # foo_0-000000000...save.txz
        with tarfile.open('temp/' + archive_name, 'w') as tar:
            tar.add(save_path, arcname=os.path.basename(save_path))

        end_tar_time = time.time()
        print(f'The tarring took {end_tar_time - tar_time} seconds')

        upload_time = time.time()

        file_meta = {'title': archive_name, 'parents': [{'id': root_id}]}
        fileitem = self.drive.CreateFile(file_meta)
        fileitem.SetContentFile('temp/' + archive_name)
        fileitem.Upload()
        fileitem.content.close()

        end_upload = time.time()
        print(f'the upload took {end_upload - upload_time} seconds')

        os.remove('temp/' + archive_name)

        game_config['saves'].append(fileitem['id'])
        self.local_config['games'][local_index] = local_config
        self.update_local_config()
        self.remote_config_handler(index=cloud_index, **game_config)

        end_push = time.time()

        print(f'The entire push took {end_push - push_time} seconds.')

    def pull(self, local_index, save_index=-1):
        """Download and extract a game save

        :param int local_index: The index of the local game config
        :param int save_index: The index of the save in the 'saves' list on the cloud. Defaults to -1.
        """

        # Data we will be using
        game_config = self.local_config['games'][local_index]
        extract_path = os.path.split(game_config['path'])[0]
        cloud_index = game_config['cloud_index']

        cloud_config = self.remote_config_handler(index=cloud_index)
        save_id = cloud_config['saves'][save_index]

        fileitem = self.drive.CreateFile({'id': save_id})

        fileitem.GetContentFile('temp/' + fileitem['title'])

        with tarfile.open('temp/' + fileitem['title'], 'r') as tar:
            tar.extractall(extract_path)

    def sync(self, local_index):
        """Sync changes using the newest possible revision

        :param int local_index: The index of the game config in the local settings.
        """

        if self.diff(local_index) and self.diff(local_index, diff_local=False):
            # Changes made locally, changes made remotely (conflict)
            print("Save conflict")  # TODO: Figure this out
        elif not self.diff(local_index) and self.diff(local_index, diff_local=False):
            # No changes locally, changes made remotely (pull)
            self.pull(local_index)
        elif self.diff(local_index) and not self.diff(local_index, diff_local=False):
            # Changes made locally, no changes remotely (push)
            self.push(local_index)
        else:
            # No changes on local or remote end
            pass  # TODO: Log this


# TODO: NOTE: code below gets time:
"""
timestamp = name.split('-')[-1]
save_time = datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d, %I:%M:%S %p')
"""
#
# session = SyncSession()
#
# session.authenticate()
# session.diff(0)
# blah = session.local_config['games'][0]
# # session.config_handler(delete=True, index=0)
# session.upload_save("C:\\Users\\Sam\\Saved Games\\Arkane Studios\\Dishonored2\\base\\savegame", 1)
# print(session.config_handler())
# session.add_game_entry("Dishonored 2")
# session.enable_game_entry(1, 'C:\\Users\\Sam\\Saved Games\\Arkane Studios\\Dishonored2\\base\\savegame')
# print("\n\n\n")


# base_root = os.path.split("C:\\Users\\ponch\\PycharmProjects\\gdrive-gamepass\\testsave")[0]
# for root, dirs, files in os.walk("C:\\Users\\ponch\\PycharmProjects\\gdrive-gamepass\\testsave"):
#     for dire in dirs:
#         print(root.replace(base_root, '') + '\\\\' + dire)

end_time = time.time()

print(f"complete in {end_time - start_time}")
# 
# dict1 = {"item3": "fs daafvac", "item1": "thingsonfl", "item2": "dahdklahldajhl"}
# dict2 = {"item2": "adasd gg", "item1": "nstavgafb", "item3": "fs vac"}
# 
# if dict1.keys() == dict2.keys():
#     print("h")
