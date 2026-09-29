def upload_file(system, *, workspace_id, file_id=None, filename="guide.txt", data=b"hello"):
    client = system["client"]
    headers = system["headers"]
    target = {"file_id": file_id} if file_id else {}
    base = f"/api/v1/workspaces/{workspace_id}/files"
    prepared = client.post(
        f"{base}/upload-url",
        json=target | {"filename": filename},
        headers=headers,
    )
    assert prepared.status_code == 200, prepared.text
    upload = prepared.json()
    system["storage"].objects[upload["s3_url"]] = data
    completed = client.post(
        f"{base}/{upload['file_id']}/complete",
        json={"s3_url": upload["s3_url"], "filename": filename},
        headers=headers,
    )
    assert completed.status_code == 202, completed.text
    return completed.json()
