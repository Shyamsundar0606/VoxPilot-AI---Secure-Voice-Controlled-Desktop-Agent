"""Windows-specific behavior kept behind an injectable adapter."""
import ctypes
import os
from pathlib import Path
from uuid import UUID

from app.security.filesystem_policy import FilePolicyError


class WindowsFolders:
    IDS = {
        "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
        "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
        "downloads": "374DE290-123F-4565-9164-39C4925E467B",
        "pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
        "music": "4BD8D571-6D19-48D3-BE97-422220080E43",
        "videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
    }

    def known_roots(self):
        if os.name != "nt": raise FilePolicyError("Windows 11 is required.")
        roots = {}
        api = ctypes.windll.shell32.SHGetKnownFolderPath
        api.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        api.restype = ctypes.c_long
        free = ctypes.windll.ole32.CoTaskMemFree
        free.argtypes = [ctypes.c_void_p]
        for name, identifier in self.IDS.items():
            guid = ctypes.create_string_buffer(UUID(identifier).bytes_le)
            pointer = ctypes.c_void_p()
            if api(guid, 0, None, ctypes.byref(pointer)) == 0:
                try: roots[name] = Path(ctypes.wstring_at(pointer))
                finally: free(pointer)
        return roots

    def fixed_drive(self, path):
        if os.name != "nt": return False
        api = ctypes.windll.kernel32.GetDriveTypeW
        api.argtypes = [ctypes.c_wchar_p]
        api.restype = ctypes.c_uint
        return api(str(Path(path).anchor)) == 3

    def open_folder(self, path):
        # Only called with a freshly validated directory, never a file or command.
        os.startfile(str(path), "open")

    def open_document(self, path):
        """Knowledge citations only; caller revalidates approval and content identity."""
        from app.knowledge.discovery import safe_source
        from app.security.filesystem_policy import check_path_chain
        safe_source(Path(path).name)
        check_path_chain(Path(path))
        if not Path(path).is_file(): raise FilePolicyError('Source is not a file.')
        os.startfile(str(path), 'open')
