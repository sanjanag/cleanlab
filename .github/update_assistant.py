import os

from openai import OpenAI

if __name__ == "__main__":
    openai_client = OpenAI()
    assistant_id = os.environ["OPENAI_ASSISTANT_ID"]
    assistant = openai_client.beta.assistants.retrieve(assistant_id)

    # Ready the files for upload to OpenAI
    file_extensions = [".html"]
    file_paths = []
    for root, dirs, files in os.walk(os.getcwd() + "/cleanlab-docs/stable"):
        for file in files:
            if any(file.endswith(ext) for ext in file_extensions):
                file_paths.append(os.path.join(root, file))
    print("Number of files:", len(file_paths))
    file_streams = [open(path, "rb") for path in file_paths]

    current_vector_stores = assistant.tool_resources.file_search.vector_store_ids
    assert len(current_vector_stores) == 1

    current_vector_store_id = current_vector_stores[0]
    new_vector_store = openai_client.beta.vector_stores.create(name="HTML Docs")

    file_batch = openai_client.beta.vector_stores.file_batches.upload_and_poll(
        vector_store_id=new_vector_store.id, files=file_streams
    )
    print(f"Uploaded files to vector store: {new_vector_store.id}")
    assistant = openai_client.beta.assistants.update(
        assistant_id=assistant_id,
        tool_resources={"file_search": {"vector_store_ids": [new_vector_store.id]}},
    )

    openai_client.beta.vector_stores.delete(vector_store_id=current_vector_store_id)
    print(f"Deleted vector store {current_vector_store_id}")
