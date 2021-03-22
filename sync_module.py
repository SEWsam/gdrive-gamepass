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
import os
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
from pydrive.files import ApiRequestError
import time
import json
import hashlib

start_time = time.time()


def hash_file(filepath, md5=False):
    """Hash a single file, using sha1 or md5

    :param str filepath: Path to the file to be hashed.
    :param bool md5: Whether or not to use md5 instead of sha1. Default: False
    """
    if md5:
        hash_obj = hashlib.md5()
    else:
        hash_obj = hashlib.sha1()

    with open(filepath, 'rb') as f:
        while True:
            block = f.read(2 ** 10)
            if not block:
                break
            hash_obj.update(block)

        return hash_obj.hexdigest()


def hash_dir(path):
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

    def config_handler(self, delete=False, index=None, **kwargs):
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

    def initialize_gdrive(self, old_folder, old_config):
        """Initialize App in Google Drive"""

        self.save_folder = old_folder or self.drive.CreateFile(
            {'title': 'Gamepass Saves', 'mimeType': 'application/vnd.google-apps.folder'}
        )
        self.save_folder.Upload()

        self.app_config = old_config or self.drive.CreateFile(
            {'title': 'config.json', 'mimeType': 'application/json', 'parents': [{'id': self.save_folder['id']}]}
        )
        self.app_config.SetContentString('{"base_revision": 0, "games": []}')
        self.app_config.Upload()

    def authenticate(self):
        """Authenticate with google drive"""

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

        if self.save_folder is None:
            self.initialize_gdrive(self.save_folder, self.app_config)

        app_data = self.drive.ListFile(
            {"q": f"'{self.save_folder['id']}' in parents and mimeType='application/json' and trashed=false"}
        ).GetList()

        for i in app_data:
            if i['title'] == 'config.json':
                self.app_config = i
                break

        if self.app_config is None:
            self.initialize_gdrive(self.save_folder, self.app_config)

        print(self.save_folder['id'])
        print(self.app_config['id'])

    def diff(self, local_index):
        """Determine whether the remote save differs from the local copy
        
        :param int local_index: The index of the game info in the local config
        :returns: True if the saves are different.
        :rtype: bool
        """
        
        game_config = self.local_config['games'][local_index]
        cloud_config = self.config_handler(index=game_config['cloud_index'])
        local_hash = hash_dir(game_config['path'])
        cloud_hash = cloud_config['hash']
        
        if cloud_hash == local_hash:
            return False
        else:
            return True

    def init_directories(self, root_id, root, dirname, parent_ids):
        """Create dirs and subdirs based on the path and existing dirs."""

        create_start = time.time()  # TODO: DEBUG

        # Over-commenting because I want to come back and improve this
        # Dirname = title of folder = d in dirs
        folder_meta = {'title': dirname, 'mimeType': 'application/vnd.google-apps.folder'}
        # If the parent of this dir is not the root of the entire gamesave, match the existing parent
        if root in parent_ids:
            folder_meta.update(parents=[{'id': parent_ids[root]}])
        else:
            folder_meta.update(parents=[{'id': root_id}])  # Otherwise, create this in the root of the gamesave

        folder = self.drive.CreateFile(folder_meta)

        folder.Upload()
        create_end = time.time()  # TODO: DEBUG
        print(f"That folder took {create_end - create_start}")  # TODO: DEBUG

        return {os.path.join(root, dirname): folder['id']}  # Return the ID for use as a parent dir later

    def upload_files(self):
        """Upload or update existing files accordingly"""
        pass

    def upload_save(self, index):
        """Create new dirs and overwrite files recursively in a chosen dir"""

        local_config = self.local_config['games'][index]
        path = local_config['path']
        cloud_index = local_config['cloud_index']
        roots = os.path.split(path)
        sys_root = roots[0]
        save_root = roots[1]
        game_config = self.config_handler(index=cloud_index)
        parent_ids = game_config['parent_ids']
        file_ids = game_config['file_ids']
        root_id = game_config['root_id']

        # Find locally deleted files and update the cloud
        # todo: dir_set - parent_ids.keys() | file_set = file_ids.keys()
        dir_set = {save_root}
        file_set = set()

        # Save metadata
        # todo: add time
        self.config_handler(index=cloud_index, hash=hash_dir(path))

        # TODO: Possibly fix redundancy?
        if save_root not in parent_ids:
            parent_ids.update(
                **self.init_directories(root_id=root_id, root='', dirname=save_root, parent_ids=parent_ids)
            )

        # Initialize directories. If the directory is already present on the cloud ['parent_ids'], it is ignored.
        for root, dirs, files in os.walk(path):
            relative_root = root.replace(sys_root, '')[1:]
            for d in dirs:
                dir_set.add(os.path.join(relative_root, d))

                if os.path.join(relative_root, d) not in parent_ids:
                    dir_kwargs = {'root_id': self.config_handler(index=cloud_index)['root_id'],
                                  'root': relative_root,
                                  'dirname': d,
                                  'parent_ids': parent_ids}

                    parent_ids.update(**self.init_directories(**dir_kwargs))

        # Delete dirs not present locally
        deleted_dirs = parent_ids.keys() - dir_set
        for del_dir in deleted_dirs:
            i = game_config['parent_ids'].pop(del_dir)
            dir_file = self.drive.CreateFile({'id': i})
            try:
                dir_file.Delete()
            except ApiRequestError:
                pass

        # Upload/update files. If the file already exists on the cloud ['file_ids'], overwrite it.
        # TODO: Detect removed files
        for root, dirs, files in os.walk(path):
            relative_root = root.replace(sys_root, '')[1:]
            for f in files:
                filepath = os.path.join(relative_root, f)
                file_set.add(filepath)

                if filepath in file_ids:
                    file_meta = {'id': file_ids[filepath]}
                else:
                    file_meta = {'title': f, 'parents': [{'id': parent_ids[relative_root]}]}

                fileitem = self.drive.CreateFile(file_meta)

                if filepath in file_ids:
                    cloudfile_hash = fileitem['md5Checksum']
                    localfile_hash = hash_file(os.path.join(root, f), md5=True)

                    if cloudfile_hash == localfile_hash:
                        return

                fileitem.SetContentFile(os.path.join(root, f))
                fileitem.Upload()
                new_data = {filepath: fileitem['id']}
                file_ids.update(**new_data)

        # Delete files not present locally
        deleted_files = file_ids.keys() - file_set
        for del_file in deleted_files:
            i = game_config['file_ids'].pop(del_file)
            dir_file = self.drive.CreateFile({'id': i})
            try:
                dir_file.Delete()
            except ApiRequestError:
                pass

        self.config_handler(index=index, file_ids=file_ids, parent_ids=parent_ids)

    def add_game_entry(self, name):
        self.config_handler(name=name, parent_ids={}, file_ids={})
        save_root = self.drive.CreateFile(
            {
                'title': f"{name}-{len(self.config_handler()) - 1}",
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [{'id': self.save_folder['id']}]
            }
        )
        save_root.Upload()

        self.config_handler(index=-1, root_id=save_root['id'])

    def enable_game_entry(self, cloud_index, path):
        game_entry = self.config_handler(index=cloud_index)
        local_entry = {'name': game_entry['name'], 'cloud_index': cloud_index, 'path': path}
        
        self.local_config['games'].append(local_entry)
        self.update_local_config()

    def push(self, local_index):
        pass


#
# session = SyncSession()
#
# session.authenticate()
# blah = session.local_config['games'][0]
# # session.config_handler(delete=True, index=0)
# session.upload_save("C:\\Users\\Sam\\Saved Games\\Arkane Studios\\Dishonored2\\base\\savegame", 1)
# print(session.config_handler())
# session.add_game_entry("Dishonored 2")
# session.enable_game_entry(1, 'C:\\Users\\Sam\\Saved Games\\Arkane Studios\\Dishonored2\\base\\savegame')
# print("\n\n\n")


# session.upload_folder('testsave')
# filelol = session.drive.CreateFile({'id': 'breuh'})

# jsonobj = json.loads(session.app_config.GetContentString())
#
#
# session.app_config.SetContentString(json.dumps(jsonobj, indent=4))
# session.app_config.Upload()
#
# jsondict = dict(jsonobj)
# print(jsondict)


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
