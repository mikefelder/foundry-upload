#!/usr/bin/env python3
"""
Server-side file upload for Ted's Foundry agent (File Search / vector store).

Why this exists:
  The Foundry portal uploads a file by handing the BROWSER a short-lived
  `upload_url` (a blob SAS URL) and PUTting the bytes directly to storage.
  On this landing zone that path is blocked (private storage + account-key
  access disabled + client DNS resolving to the public endpoint). This script
  bypasses all of that: it sends the bytes to the Foundry PROJECT endpoint over
  Entra ID, and the SERVICE writes them to storage using its managed identity --
  the same server-side path that already works for index creation.

Prereqs:
  pip install azure-ai-projects azure-identity
  az login            (as a user with 'Azure AI User' on the project, e.g. Ted or Samir)

Run:
  export FOUNDRY_PROJECT_ENDPOINT="https://ai-foundry-s50j.services.ai.azure.com/api/projects/aif-prj-dev-02"
  # ^ grab the exact value from Foundry portal -> your project -> Overview -> "Project endpoint"
  python upload_files.py --agent-id <asst_xxx>        # attach to Ted's existing agent
  # ...or omit --agent-id to just create the vector store and print its id.

Drop the files Ted needs indexed into the ./files folder next to this script.
"""
import argparse
import os
import sys

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--files-dir",
        default=os.path.join(os.path.dirname(__file__), "files"),
        help="Folder of files to upload (default: ./files)",
    )
    parser.add_argument(
        "--vector-store-name",
        default="ted-filesearch",
        help="Name for the vector store to create",
    )
    parser.add_argument(
        "--agent-id",
        default=None,
        help="Optional existing agent id (asst_...) to attach the vector store to via file_search",
    )
    args = parser.parse_args()

    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        print("ERROR: set FOUNDRY_PROJECT_ENDPOINT (see header of this file).", file=sys.stderr)
        return 2

    files = [
        os.path.join(args.files_dir, f)
        for f in sorted(os.listdir(args.files_dir))
        if os.path.isfile(os.path.join(args.files_dir, f))
    ]
    if not files:
        print(f"ERROR: no files found in {args.files_dir}. Drop Ted's docs there first.", file=sys.stderr)
        return 2

    project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    agents = project.agents  # AgentsClient

    print(f"Uploading {len(files)} file(s) server-side over Entra ID...")
    file_ids = []
    for path in files:
        uploaded = agents.files.upload_and_poll(file_path=path, purpose="assistants")
        file_ids.append(uploaded.id)
        print(f"  + {os.path.basename(path)} -> {uploaded.id}")

    print("Creating vector store and indexing...")
    vector_store = agents.vector_stores.create_and_poll(
        file_ids=file_ids, name=args.vector_store_name
    )
    print(f"Vector store ready: {vector_store.id} (status={vector_store.status})")

    if args.agent_id:
        from azure.ai.agents.models import FileSearchTool

        file_search = FileSearchTool(vector_store_ids=[vector_store.id])
        agents.update_agent(
            agent_id=args.agent_id,
            tools=file_search.definitions,
            tool_resources=file_search.resources,
        )
        print(f"Attached vector store to agent {args.agent_id}. File Search is live.")
    else:
        print(
            "Done. To use it, add a File Search tool on Ted's agent pointing at "
            f"vector store id: {vector_store.id}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
