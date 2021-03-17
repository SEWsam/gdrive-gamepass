"""
Copyright (c) 2021 Samuel Wirth

Licensed under the MIT License. See LICENSE for more info.
"""
import os
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive, GoogleDriveFile
import time
import json

start_time = time.time()


class SyncSession:
    def __init__(self):
        self.drive = None
        self.save_folder = None
        self.app_config = None
        with open('settings.json', 'r') as f:
            self.local_config = json.load(f)

    @property
    def app_config_json(self):
        try:
            return json.loads(self.app_config.GetContentString())
        except AttributeError:
            return None

    def update_local_config(self):
        """Update local config file to match changes"""

        with open('settings.json', 'w') as f:
            f.write(json.dumps(self.local_config))

    def config_handler(self, delete=False, index=None, **kwargs):
        """Read and write to the remote config['games']

        :param bool delete: When True, the selected index is deleted and the 'base_revision' is incremented
        :param int index: Optional. The index of the game item to return. Defaults to None, which returns all values.
        :param kwargs: Optional: Write values in config.
        :returns: Modified config.
        """
        working_json = self.app_config_json
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

        # TODO: speed this up by forcing parent to be root
        folders = self.drive.ListFile(
            {"q": "mimeType='application/vnd.google-apps.folder' and trashed=false"}
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

    # TODO: ADD HASHING

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

    def upload_save(self, path, index):
        """Create new dirs and overwrite files recursively in a chosen dir"""

        roots = os.path.split(path)
        sys_root = roots[0]
        save_root = roots[1]
        # TODO: Speed this up with one call
        parent_ids = self.config_handler(index=index)['parent_ids']
        file_data = self.config_handler(index=index)['file_data']
        root_id = self.config_handler(index=index)['root_id']

        # TODO: Possibly fix redundancy?
        if save_root not in parent_ids:
            parent_ids.update(
                **self.init_directories(root_id=root_id, root='', dirname=save_root, parent_ids=parent_ids)
            )

        # Initialize directories. If the directory is already present on the cloud ['parent_ids'], it is ignored.
        for root, dirs, files in os.walk(path):
            for d in dirs:
                if os.path.join(root.replace(sys_root, '')[1:], d) not in parent_ids:
                    dir_kwargs = {'root_id': self.config_handler(index=index)['root_id'],
                                  'root': root.replace(sys_root, '')[1:],
                                  'dirname': d,
                                  'parent_ids': parent_ids}

                    parent_ids.update(**self.init_directories(**dir_kwargs))

        # Upload/update files. If the file already exists on the cloud ['file_data'], overwrite it.
        # TODO: Detect removed files
        for root, dirs, files in os.walk(path):
            for f in files:
                filepath = os.path.join(root.replace(sys_root, '')[1:], f)


                if filepath in file_data:
                    file_meta = {'id': file_data[filepath]['id']}
                else:
                    file_meta = {'title': f, 'parents': [{'id': parent_ids[root.replace(sys_root, '')[1:]]}]}

                fileitem = self.drive.CreateFile(file_meta)
                fileitem.SetContentFile(os.path.join(root, f))
                fileitem.Upload()
                new_data = {filepath: {'id': fileitem['id'], 'hash': 'nothing yet'}}
                file_data.update(**new_data)

                self.config_handler(index=index, file_data=file_data)

        self.config_handler(index=index, parent_ids=parent_ids)

    def add_game_entry(self, name):
        self.config_handler(name=name, parent_ids={}, file_data={})
        save_root = self.drive.CreateFile(
            {
                'title': f"{name}-{len(self.app_config_json['games']) - 1}",
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [{'id': self.save_folder['id']}]
            }
        )
        save_root.Upload()

        self.config_handler(index=-1, root_id=save_root['id'])

    def enable_game_entry(self, index, path):
        game_entry = self.config_handler(index=index)

        with open('settings.json', 'r') as f:
            settings = json.load(f)

        local_entry = {'name': game_entry['name'], 'cloud_index': index, 'path': path}
        settings['games'].append(local_entry)

        with open('settings.json', 'w') as f:
            f.write(json.dumps(settings, indent=4))

    def push(self, index):
        pass



# session = SyncSession()
# #
# session.authenticate()
# # session.config_handler(delete=True, index=0)
# session.upload_save("C:/Users/ponch/PycharmProjects/gdrive-gamepass/testsave", 0)
# print(session.config_handler())
# # session.add_game_entry("Prey")
# # session.enable_game_entry(0, "C:\\Users\\ponch\\PycharmProjects\\gdrive-gamepass\\testsave")
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
