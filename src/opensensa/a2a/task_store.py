# ===========================================================================
# Copyright (C) 2025 CapsicoHealth Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ===========================================================================

"""A2A Task Store — re-exports InMemoryTaskStore from a2a-sdk.

For v1, we use the SDK's in-memory implementation. Swap to a DB-backed
store (e.g. a2a-sdk's DatabaseTaskStore with SQLAlchemy) when persistence
is needed.
"""

from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore

__all__ = ["InMemoryTaskStore"]
