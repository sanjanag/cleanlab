import json
import os

from openai import OpenAI


def get_changed_files(docs_dir, branch):
    os.system(
        f"git -C {docs_dir} diff --name-only --output changed_files.txt HEAD HEAD~1 {branch}/"
    )
    with open(f"{docs_dir}/changed_files.txt", "r") as f:
        changed_files = f.readlines()
    changed_files = [changed_file.strip() for changed_file in changed_files]
    changed_files = [file for file in changed_files if file.endswith(".html")]
    changed_files = [file[len(branch) + 1 :] for file in changed_files]
    return changed_files


if __name__ == "__main__":

    branch = "master"
    docs_dir = os.path.join(os.getcwd(), "cleanlab-docs")
    mapping_path = os.path.join(os.getcwd(), "main", ".github/openai_file_mapping.json")
    vector_store_id = os.environ["OPENAI_VECTOR_STORE_ID"]

    changed_files = get_changed_files(docs_dir, branch)
    print("Changed files:")
    for file in changed_files:
        print(file)

    print("Deleting stale files")
    with open("openai_file_mapping.json", "r") as f:
        openai_file_mappping = json.load(f)

    client = OpenAI()

    for file in changed_files:
        file_id = openai_file_mappping.get(file, None)
        if file_id:
            print(f"Deleting file, path: {file}, file_id: {file_id}")
            client.beta.vector_stores.files.delete(vector_store_id=vector_store_id, file_id=file_id)
            client.files.delete(file_id)

    print("Uploading changed files")
    new_files = [
        client.files.create(
            file=open(os.path.join(docs_dir, branch, file_path), "rb"), purpose="assistants"
        )
        for file_path in changed_files
    ]
    changed_files_mapping = {filepath: file.id for filepath, file in zip(changed_files, new_files)}

    print("Uploading changed files as vector store files")
    vector_store_files = [
        client.beta.vector_stores.files.create(vector_store_id=vector_store_id, file_id=file.id)
        for file in new_files
    ]
    new_openai_file_mappping = {**openai_file_mappping, **changed_files_mapping}

    print("Writing new mapping")
    with open(mapping_path, "w") as f:
        json.dump(new_openai_file_mappping, f)
