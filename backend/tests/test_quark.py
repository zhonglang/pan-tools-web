import httpx

from app.pans import adapter_for

COOKIE = "b-user-id=1"


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_list_dir_maps_root_and_folder_type():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["pdir_fid"] == "0"
        return httpx.Response(
            200,
            json={
                "status": 200,
                "data": {
                    "list": [
                        {"fid": "folder-1", "file_name": "电影", "file_type": 0, "size": 0, "updated_at": 1700000000000},
                        {"fid": "file-1", "file_name": "a.mp4", "file_type": 1, "size": 12, "updated_at": 1700000000000},
                    ]
                },
            },
        )

    rows = adapter_for("quark", client_for(handler)).list_dir(COOKIE, "/")
    assert rows[0].name == "电影" and rows[0].is_dir and rows[0].path == "/folder-1"
    assert rows[1].name == "a.mp4" and rows[1].is_dir is False and rows[1].path == "/file-1"


def test_create_rename_delete_use_fid():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.read()))
        return httpx.Response(200, json={"status": 200, "data": {"fid": "new-1"}})

    adapter = adapter_for("quark", client_for(handler))
    created = adapter.create_dir(COOKIE, "/", "新文件夹")
    adapter.rename(COOKIE, "/folder-1", "新名字")
    adapter.delete(COOKIE, "/file-1")
    assert created.path == "/new-1"
    assert "/1/clouddrive/file/rename" in seen[1][1]
    assert b"file-1" in seen[2][2]
