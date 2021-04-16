"""savemgr.py: Manages local and cloud game saves.

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
import random
from typing import Callable
import json
import os
import shutil
import tarfile
import time
import logging

from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive

start_time = time.time()

logger = logging.getLogger(__name__)


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


class ManagerSession:
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
        self.app_folder = None
        self.app_config = None
        with open('settings.json', 'r') as f:
            self.local_config = json.load(f)

    def update_local_config(self):
        """Update local config file to match changes"""

        with open('settings.json', 'w') as f:
            logger.debug(f"Writing changes to local config file: {self.local_config}")
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
            logger.debug(f"Loaded current remote config: {working_json}")
        except AttributeError:
            logger.error("Error loading config.")
            logger.debug("Config error: Possibly not authenticated/Unknown initialization error")
            return None

        if not delete:
            if index is not None:
                if kwargs:
                    working_json['games'][index].update(**kwargs)
                    logger.debug(f"Updated values for game[{index}] with {kwargs}")

                return_value = working_json['games'][index]
            else:
                if kwargs:
                    working_json['games'].append(kwargs)
                    logger.debug(f"Added game entry: {kwargs}")

                return_value = working_json['games']
        else:
            if kwargs:
                raise ValueError("Unexpected keyword arg(s) in deletion mode.")

            working_json['games'].pop(index)
            working_json.update(base_revision=working_json['base_revision'] + 1)
            logger.debug(f"Deleted game entry at index: {index}")

            return_value = working_json['games']

        if kwargs or delete:
            self.app_config.SetContentString(json.dumps(working_json, indent=4))
            self.app_config.Upload()
            logger.debug("Uploaded config changes to remote.")

        logger.debug(f"Fetched config json: {return_value}")
        return return_value

    def initialize_gdrive(self, original=None):
        """Initialize App in Google Drive; create app folder and config.

        :param original: Preexisting app folder if applicable.
        """

        logger.info("Setting up Google Drive")

        self.app_folder = original or self.drive.CreateFile(
            {'title': 'Gamepass Saves', 'mimeType': 'application/vnd.google-apps.folder'}
        )
        self.app_folder.Upload()
        logger.debug("Created/re-uploaded app folder")

        self.app_config = self.drive.CreateFile(
            {'title': 'config.json', 'mimeType': 'application/json', 'parents': [{'id': self.app_folder['id']}]}
        )
        self.app_config.SetContentString('{"base_revision": 0, "games": []}')
        self.app_config.Upload()
        logger.debug("Created and uploaded base app config file.")

    def authenticate(self):
        """Create an authenticated drive session."""

        # The settings used allow app-only files to be changed, and credentials are saved
        gauth = GoogleAuth(settings_file='authentication/settings.yaml')
        logger.debug("Loaded config file")

        gauth.LoadCredentialsFile()
        logger.debug(f"Loaded Credentials: {gauth.credentials}")

        if gauth.credentials is None:
            logger.warning("Login Required. Opening browser momentarily.")
            time.sleep(2)

        self.drive = GoogleDrive(gauth)
        logger.debug("Created GoogleDrive instance")

        query = "'root' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        folder_search = self.drive.ListFile({"q": query}).GetList()
        logger.debug(f"Searched with query: {query}")

        if not folder_search:
            logger.debug("Could not locate app folder.")
            self.initialize_gdrive()
            return

        for i in folder_search:
            if i['title'] == 'Gamepass Saves':
                self.app_folder = i
                logger.debug("Located app folder.")
                break

        query = f"'{self.app_folder['id']}' in parents and mimeType='application/json' and trashed=false"
        config_search = self.drive.ListFile({"q": query}).GetList()
        logger.debug(f"Searched with query: {query}")

        if not config_search:
            logger.debug("Could not locate app config.")
            self.initialize_gdrive(self.app_folder)
            return

        for i in config_search:
            if i['title'] == 'config.json':
                self.app_config = i
                logger.debug("Located app config")
                break

        logger.debug(f"App folder ID: {self.app_folder['id']}")
        logger.debug(f"App config ID: {self.app_config['id']}")

    def diff(self, local_index, diff_local=True):
        """Determine whether the current save has changed locally or if it differs from the remote gamesave
        
        :param int local_index: The index of the game info in the local config
        :param bool diff_local: Check the base version against the current gamesave. Defaults to True.
        :returns: True if the saves are different.
        :rtype: bool
        """

        game_config = self.local_config['games'][local_index]
        base_hash = game_config['base_hash']
        logger.debug(f"Hash of save, at last sync was: {base_hash}")

        if diff_local:
            current_hash = hash_dir(game_config['path'])
            logger.debug(f"Current save hash for local index '{local_index}': {current_hash}")

            if current_hash == base_hash:
                logger.debug(f"No changes detected locally. Local index: '{local_index}'")
                return False
            else:
                logger.debug(f"Changes detected locally since last sync. Local index: '{local_index}'")
                return True
        else:
            cloud_config = self.remote_config_handler(index=game_config['cloud_index'])
            cloud_hash = cloud_config['latest_hash']
            logger.debug(f"Current save hash for latest remote save: {cloud_hash} (Local index: {local_index})")

            if cloud_hash == base_hash:
                logger.debug(f"Last sync matches latest remote save")
                return False
            else:
                logger.debug(f"Last sync DOES NOT match latest remote save")
                return True

    def add_game_entry(self, name):
        self.remote_config_handler(name=name, saves=[], latest_hash='da39a3ee5e6b4b0d3255bfef95601890afd80709')

        root_title = f"{name}_{len(self.remote_config_handler()) - 1}"
        save_root = self.drive.CreateFile(
            {
                'title': root_title,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [{'id': self.app_folder['id']}]
            }
        )
        save_root.Upload()
        logger.debug(f"Created and uploaded save root folder with name {root_title}")

        self.remote_config_handler(index=-1, root_id=save_root['id'])

    def enable_game_entry(self, cloud_index, path):
        game_entry = self.remote_config_handler(index=cloud_index)
        local_entry = {'name': game_entry['name'], 'cloud_index': cloud_index,
                       'path': path, 'base_hash': 'da39a3ee5e6b4b0d3255bfef95601890afd80709'}

        self.local_config['games'].append(local_entry)
        self.update_local_config()

    def push(self, local_index, progress_callback=lambda *x: None):
        """Upload saves as tarballs, keeping a history of saves

        :param local_index: The index of the game config in the local settings.
        :param progress_callback: Callback object for progress: Callable(progress: int, local_index: int)
        """

        push_time = time.time()

        # Data we will be using
        local_config = self.local_config['games'][local_index]
        game_name = local_config['name']
        save_path = local_config['path']
        cloud_index = local_config['cloud_index']

        logger.info(f"Pushing {game_name}")

        game_config = self.remote_config_handler(index=cloud_index)
        root_id = game_config['root_id']

        # Get the save's hash
        save_hash = hash_dir(save_path)
        game_config['latest_hash'] = save_hash
        local_config['base_hash'] = save_hash


        tar_time = time.time()
        print(str(self.local_config) + " tarring " + str(local_index))

        archive_name = f'{game_name}_{cloud_index}-{time.time()}.save.tar'  # foo_0-000000000...save.txz
        with tarfile.open('temp/' + archive_name, 'w:') as tar:
            tar.add(save_path, arcname=os.path.basename(save_path))


        end_tar_time = time.time()
        logger.info(f'The tarring took {end_tar_time - tar_time} seconds ' + str(local_index))

        upload_time = time.time()

        file_meta = {'title': archive_name, 'parents': [{'id': root_id}]}
        fileitem = self.drive.CreateFile(file_meta)
        fileitem.SetContentFile('temp/' + archive_name)
        fileitem.Upload()
        fileitem.content.close()


        end_upload = time.time()
        logger.info(f'the upload took {end_upload - upload_time} seconds ' + str(local_index))

        # os.remove('temp/' + archive_name)

        game_config['saves'].append(fileitem['id'])
        self.local_config['games'][local_index] = local_config
        self.update_local_config()
        self.remote_config_handler(index=cloud_index, **game_config)


        end_push = time.time()

        logger.info(f'The entire push took {end_push - push_time} seconds. ' + str(local_index))

    def pull(self, local_index, save_index=-1, progress_callback=lambda *x: None):
        """Download and extract a game save

        :param int local_index: The index of the local game config
        :param int save_index: The index of the save in the 'saves' list on the cloud. Defaults to -1.
        :param progress_callback: Callback object for progress: Callable(progress: int, local_index: int)
        """

        # Data we will be using
        local_config = self.local_config['games'][local_index]
        save_path = local_config['path']
        extract_path = os.path.split(save_path)[0]
        cloud_index = local_config['cloud_index']

        cloud_config = self.remote_config_handler(index=cloud_index)
        save_id = cloud_config['saves'][save_index]
        local_config['base_hash'] = cloud_config['latest_hash']

        progress_callback(25, local_index)

        fileitem = self.drive.CreateFile({'id': save_id})

        logger.info("Downloading: " + str(local_index))
        fileitem.GetContentFile('temp/' + fileitem['title'])
        progress_callback(50, local_index)

        shutil.rmtree(save_path)

        logger.info("Extracting: " + str(local_index))
        with tarfile.open('temp/' + fileitem['title'], 'r') as tar:
            tar.extractall(extract_path)

        progress_callback(75, local_index)

        os.remove('temp/' + fileitem['title'])

        self.update_local_config()
        progress_callback(100, local_index)

    def sync(self, local_index, progress_callback=lambda *x: None):
        """Sync changes using the newest possible revision

        :param int local_index: The index of the game config in the local settings.
        :param progress_callback: Callback object for progress: Callable(progress: int, local_index: int).
                                  Passed to push() and pull() methods.
        """

        local_config = self.local_config['games'][local_index]
        saves_list = self.remote_config_handler(index=local_config['cloud_index'])

        if self.diff(local_index) and self.diff(local_index, diff_local=False):
            # Changes made locally, changes made remotely (conflict)
            logger.info("Conflict " + str(local_index))
            return saves_list
        elif not self.diff(local_index) and self.diff(local_index, diff_local=False):
            # No changes locally, changes made remotely (pull)
            logger.info("Pulling " + str(local_index))
            self.pull(local_index, progress_callback=progress_callback)
            logger.info("Pulled" + str(local_index))
        elif self.diff(local_index) and not self.diff(local_index, diff_local=False):
            # Changes made locally, no changes remotely (push)
            logger.info("Pushing " + str(local_index))
            # self.push(local_index, progress_callback=progress_callback) # TODO: me when the
            logger.info("Pushed" + str(local_index))
        else:
            # No changes on local or remote end
            logger.info("Nothing" + str(local_index))
            progress_callback(100, local_index)
            pass  # TODO: Log this

    def testmeth(self):
        logger.info('Testing method@ ' + str(time.time()))
        logger.debug('bruh')
        time.sleep(float(random.randint(1, 3)))
        time.sleep(float(random.randint(1, 3)))
        time.sleep(float(random.randint(1, 3)))
        time.sleep(float(random.randint(1, 3)))


# TODO: NOTE: code below gets time:
"""
timestamp = name.split('-')[-1]
save_time = datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d, %I:%M:%S %p')
"""
#
# session = ManagerSession()
# session.authenticate()
# # session.add_game_entry('Prey')
# # session.enable_game_entry(0, 'C:\\Users\\ponch\\Saved Games\\Arkane Studios\\Prey_MS\\SaveGames')
# session.sync(0)

end_time = time.time()

print(f"complete in {end_time - start_time}")
