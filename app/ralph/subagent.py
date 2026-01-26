"""Subagent schemas and prompt generation for Ralph.

Provides structured schemas for subagent tasks, replacing verbose prompt
templates with programmatic schema definitions.
"""

import json
from dataclasses import dataclass
from typing import Any, Optional

# JSON schemas for subagent return types
INVESTIGATE_SCHEMA = {
    "type": "object",
    "required": ["issue_id", "root_cause", "resolution"],
    "properties": {
        "issue_id": {
            "type": "string",
            "description": "The issue ID being investigated"
        },
        "root_cause": {
            "type": "string",
            "description": "Specific file:line reference where the problem originates"
        },
        "resolution": {
            "type": "string",
            "enum": ["task", "trivial", "out_of_scope"],
            "description": "How to resolve: create task, trivial fix, or out of scope"
        },
        "task": {
            "type": "object",
            "description": "Task to create (required if resolution='task')",
            "properties": {
                "name": {"type": "string", "description": "Short task name"},
                "notes": {
                    "type": "string",
                    "description": "Root cause: file:line. Fix: approach. Imports: list. Risk: effects."
                },
                "accept": {
                    "type": "string",
                    "description": "Measurable command + expected result"
                },
                "priority": {
                    "type": "string",
                    "enum": ["high", "medium", "low"]
                }
            },
            "required": ["name", "notes", "accept"]
        }
    }
}

VERIFY_TASK_SCHEMA = {
    "type": "object",
    "required": ["task_id", "passed"],
    "properties": {
        "task_id": {
            "type": "string",
            "description": "The task ID being verified"
        },
        "passed": {
            "type": "boolean",
            "description": "Whether acceptance criteria is satisfied"
        },
        "evidence": {
            "type": "string",
            "description": "What was found during verification"
        },
        "reason": {
            "type": "string",
            "description": "Why verification failed (only if passed=false)"
        }
    }
}

VERIFY_CRITERION_SCHEMA = {
    "type": "object",
    "required": ["criterion", "passed"],
    "properties": {
        "criterion": {
            "type": "string",
            "description": "The spec criterion text being verified"
        },
        "passed": {
            "type": "boolean",
            "description": "Whether the criterion still holds"
        },
        "evidence": {
            "type": "string",
            "description": "What was found during verification"
        },
        "reason": {
            "type": "string",
            "description": "Why it failed (only if passed=false)"
        }
    }
}

RESEARCH_SCHEMA = {
    "type": "object",
    "required": ["requirement", "current_state"],
    "properties": {
        "requirement": {
            "type": "string",
            "description": "Spec requirement being researched"
        },
        "current_state": {
            "type": "string",
            "enum": ["implemented", "partial", "missing"],
            "description": "Current implementation state"
        },
        "files_to_modify": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "lines": {"type": "string", "description": "e.g., '100-150'"},
                    "what": {"type": "string"},
                    "how": {"type": "string"}
                }
            }
        },
        "files_to_create": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "template": {"type": "string", "description": "Similar existing file"},
                    "purpose": {"type": "string"}
                }
            }
        },
        "imports_needed": {
            "type": "array",
            "items": {"type": "string"}
        },
        "patterns_to_follow": {
            "type": "string",
            "description": "Reference to similar existing code"
        },
        "verification": {
            "type": "string",
            "description": "How to verify: command + expected output"
        }
    }
}

DECOMPOSE_SCHEMA = {
    "type": "object",
    "required": ["remaining_work"],
    "properties": {
        "remaining_work": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["subtask", "files", "effort"],
                "properties": {
                    "subtask": {"type": "string", "description": "Specific piece of work"},
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "lines": {"type": "string"}
                            }
                        }
                    },
                    "effort": {
                        "type": "string",
                        "enum": ["small", "medium"],
                        "description": "Estimated effort (must be completable in one iteration)"
                    }
                }
            }
        },
        "context_risks": {
            "type": "string",
            "description": "What caused context explosion in parent task"
        },
        "mitigation": {
            "type": "string",
            "description": "How subtasks avoid the same fate"
        }
    }
}


@dataclass
class SubagentPrompt:
    """A structured subagent prompt with schema."""
    
    task_type: str
    description: str
    instructions: str
    schema: dict
    context: dict

    def render(self) -> str:
        """Render the full subagent prompt."""
        schema_json = json.dumps(self.schema, indent=2)
        context_json = json.dumps(self.context, indent=2)
        
        return f"""## Subagent Task: {self.task_type}

{self.description}

### Context
```json
{context_json}
```

### Instructions
{self.instructions}

### Required Output Format
Return a JSON object matching this schema:
```json
{schema_json}
```

Return ONLY the JSON object, no other text.
"""


def build_investigate_prompt(issue_id: str, issue_desc: str, priority: str = "medium") -> SubagentPrompt:
    """Build a subagent prompt for investigating an issue.

    Args:
        issue_id: The issue ID
        issue_desc: Issue description
        priority: Issue priority

    Returns:
        SubagentPrompt ready to render
    """
    return SubagentPrompt(
        task_type="investigate",
        description=f"Investigate issue: {issue_desc}",
        instructions="""1. Search codebase for relevant code
2. Identify the root cause with specific file:line reference
3. Determine resolution type: create task, trivial fix, or out of scope
4. If creating a task, provide detailed notes with file paths and approach""",
        schema=INVESTIGATE_SCHEMA,
        context={
            "issue_id": issue_id,
            "issue_desc": issue_desc,
            "priority": priority,
        }
    )


def build_verify_task_prompt(task_id: str, task_name: str, accept_criteria: str) -> SubagentPrompt:
    """Build a subagent prompt for verifying a task.

    Args:
        task_id: The task ID
        task_name: Task name
        accept_criteria: The acceptance criteria to verify

    Returns:
        SubagentPrompt ready to render
    """
    return SubagentPrompt(
        task_type="verify_task",
        description=f"Verify task '{task_name}' meets its acceptance criteria",
        instructions="""1. Search codebase for the implementation
2. Check if acceptance criteria is satisfied
3. Run any tests mentioned in criteria
4. Report pass/fail with evidence""",
        schema=VERIFY_TASK_SCHEMA,
        context={
            "task_id": task_id,
            "task_name": task_name,
            "accept_criteria": accept_criteria,
        }
    )


def build_verify_criterion_prompt(criterion: str, spec_file: str) -> SubagentPrompt:
    """Build a subagent prompt for verifying a spec criterion.

    Args:
        criterion: The criterion text from the spec
        spec_file: Name of the spec file

    Returns:
        SubagentPrompt ready to render
    """
    return SubagentPrompt(
        task_type="verify_criterion",
        description=f"Verify spec criterion: '{criterion}'",
        instructions="""1. Search codebase for the implementation
2. Run any tests or commands that validate this criterion
3. Check that the criterion is still satisfied
4. Report pass/fail with evidence""",
        schema=VERIFY_CRITERION_SCHEMA,
        context={
            "criterion": criterion,
            "spec_file": spec_file,
        }
    )


def build_research_prompt(requirement: str, spec_file: str) -> SubagentPrompt:
    """Build a subagent prompt for researching a spec requirement.

    Args:
        requirement: The requirement to research
        spec_file: Name of the spec file

    Returns:
        SubagentPrompt ready to render
    """
    return SubagentPrompt(
        task_type="research",
        description=f"Research requirement: {requirement}",
        instructions="""1. Analyze the codebase for current state
2. Identify files to modify with specific line ranges
3. Identify files to create with templates
4. Document imports needed and patterns to follow
5. Specify how to verify the implementation""",
        schema=RESEARCH_SCHEMA,
        context={
            "requirement": requirement,
            "spec_file": spec_file,
        }
    )


def build_decompose_prompt(task_name: str, task_notes: str, kill_reason: str) -> SubagentPrompt:
    """Build a subagent prompt for decomposing a killed task.

    Args:
        task_name: The killed task name
        task_notes: Original task notes
        kill_reason: Why the task was killed (timeout/context_limit)

    Returns:
        SubagentPrompt ready to render
    """
    return SubagentPrompt(
        task_type="decompose",
        description=f"Analyze how to decompose: {task_name}",
        instructions="""1. Identify remaining work from the killed task
2. Break down into small subtasks completable in one iteration
3. Identify what caused context explosion
4. Specify how subtasks avoid the same issue""",
        schema=DECOMPOSE_SCHEMA,
        context={
            "task_name": task_name,
            "task_notes": task_notes,
            "kill_reason": kill_reason,
        }
    )


def get_schema(task_type: str) -> Optional[dict]:
    """Get the JSON schema for a subagent task type.

    Args:
        task_type: One of: investigate, verify_task, verify_criterion, research, decompose

    Returns:
        JSON schema dict, or None if unknown type
    """
    schemas = {
        "investigate": INVESTIGATE_SCHEMA,
        "verify_task": VERIFY_TASK_SCHEMA,
        "verify_criterion": VERIFY_CRITERION_SCHEMA,
        "research": RESEARCH_SCHEMA,
        "decompose": DECOMPOSE_SCHEMA,
    }
    return schemas.get(task_type)


def validate_response(task_type: str, response: dict) -> tuple[bool, list[str]]:
    """Validate a subagent response against its schema.

    Args:
        task_type: The subagent task type
        response: The JSON response from the subagent

    Returns:
        Tuple of (is_valid, list of error messages)
    """
    schema = get_schema(task_type)
    if not schema:
        return False, [f"Unknown task type: {task_type}"]

    errors = []
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    # Check required fields
    for field in required:
        if field not in response:
            errors.append(f"Missing required field: {field}")

    # Check field types
    for field, value in response.items():
        if field in properties:
            prop = properties[field]
            expected_type = prop.get("type")
            
            if expected_type == "string" and not isinstance(value, str):
                errors.append(f"Field '{field}' must be a string")
            elif expected_type == "boolean" and not isinstance(value, bool):
                errors.append(f"Field '{field}' must be a boolean")
            elif expected_type == "array" and not isinstance(value, list):
                errors.append(f"Field '{field}' must be an array")
            elif expected_type == "object" and not isinstance(value, dict):
                errors.append(f"Field '{field}' must be an object")

            # Check enum values
            if "enum" in prop and value not in prop["enum"]:
                errors.append(f"Field '{field}' must be one of: {prop['enum']}")

    return len(errors) == 0, errors
