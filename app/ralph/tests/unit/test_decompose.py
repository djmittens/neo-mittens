import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from ...stages.decompose import _validate_subtask, run
from ...config import GlobalConfig
from ...state import RalphState
from ...models import Task
from ...stages.base import StageResult, StageOutcome


from typing import Any, Dict, Union, cast


def test_validate_subtask_valid_input():
    parent_spec = "test_spec.md"
    parent_id = "t-parent"

    # Test with minimal valid input
    data: Dict[str, Any] = {"name": "Subtask 1"}
    task = _validate_subtask(data, parent_spec, parent_id)
    assert task is not None
    assert task.name == "Subtask 1"
    assert task.spec == parent_spec
    assert task.parent == parent_id
    assert task.priority == "medium"

    # Test with full input
    data_full: Dict[str, Any] = {
        "id": "t-custom",
        "name": "Subtask 2",
        "notes": "Detailed notes",
        "priority": "high",
    }
    task_full = _validate_subtask(data_full, parent_spec, parent_id)
    assert task_full is not None
    assert task_full.id == "t-custom"
    assert task_full.name == "Subtask 2"
    assert task_full.notes == "Detailed notes"
    assert task_full.priority == "high"


def test_validate_subtask_invalid_input():
    parent_spec = "test_spec.md"
    parent_id = "t-parent"

    # Test invalid name types
    invalid_names = [None, "", " ", {}]
    for name in invalid_names:
        data: Dict[str, Any] = {"name": name}
        task = _validate_subtask(data, parent_spec, parent_id)
        assert task is None

    # Numeric and list inputs - should convert to task
    int_names = [123, 42.0]
    for name in int_names:
        data: Dict[str, Any] = {"name": name}
        task = _validate_subtask(data, parent_spec, parent_id)
        assert task is not None
        assert task.name == str(name)

    # Test non-dictionary input
    assert _validate_subtask(cast(Dict[str, Any], None), parent_spec, parent_id) is None
    assert _validate_subtask(cast(Dict[str, Any], 123), parent_spec, parent_id) is None


def test_validate_subtask_edge_cases():
    parent_spec = "test_spec.md"
    parent_id = "t-parent"

    # Test integer/float name conversion
    data: Dict[str, Any] = {"name": 42, "priority": 1}
    task = _validate_subtask(data, parent_spec, parent_id)
    assert task is not None
    assert task.name == "42"
    assert task.priority == "1"


@pytest.mark.parametrize("input_type", [str, int, float, dict])
def test_validate_subtask_priority_conversion(input_type):
    parent_spec = "test_spec.md"
    parent_id = "t-parent"

    priority: Union[str, int, float, Dict[str, str]] = (
        input_type(42) if input_type != dict else {"not_a_priority": "test"}
    )
    data: Dict[str, Any] = {"name": "Test Task", "priority": priority}

    task = _validate_subtask(data, parent_spec, parent_id)
    if input_type == dict:
        assert task is not None
        assert task.priority == "medium"
    else:
        assert task is not None
        assert task.priority == "42"
