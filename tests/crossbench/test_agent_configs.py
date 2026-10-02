# Copyright 2026 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import pathlib
import re
import tempfile
import unittest
from typing import Any, Final, Sequence

import yaml
from google.protobuf import descriptor_pb2, message_factory, text_format

from tests import test_helper

_TYPE_STR: Final[int] = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
_TYPE_MSG: Final[int] = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
_TYPE_BOOL: Final[int] = descriptor_pb2.FieldDescriptorProto.TYPE_BOOL
_EXPECTED_PROJECT: Final[str] = "crossbench"

# We do not have a default standalone validator in this repository, nor do we
# have direct access to the upstream internal CRACS protobuf schema. We define
# a minimal in-memory descriptor schema here to parse and validate
# agent_configs.textproto in tests.
_SCHEMA: Final[dict[str, list[tuple[Any, ...]]]] = {
    "Filter": [
        ("project", 1, _TYPE_STR, True),
        ("path_regex", 2, _TYPE_STR, True),
    ],
    "AgentConfig": [
        ("id", 1, _TYPE_STR, False),
        ("display_name", 2, _TYPE_STR, False),
        ("description", 3, _TYPE_STR, False),
        ("skills", 4, _TYPE_STR, True),
        ("include_filters", 5, _TYPE_MSG, True, "Filter"),
        ("exclude_filters", 6, _TYPE_MSG, True, "Filter"),
        ("automatic", 7, _TYPE_BOOL, False),
    ],
    "HostAgents": [("configs", 1, _TYPE_MSG, True, "AgentConfig")],
}


def create_host_agents_message_class() -> type[Any]:
  file_proto = descriptor_pb2.FileDescriptorProto()
  file_proto.name = "agent.proto"
  file_proto.package = (
      "google.corp.android.engprod.codereviewagentconfiguration.v1")

  for msg_name, fields in _SCHEMA.items():
    m = file_proto.message_type.add(name=msg_name)
    for field_spec in fields:
      name, num, ftype, repeated = field_spec[:4]
      type_name = field_spec[4] if len(field_spec) > 4 else None
      label = (
          descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
          if repeated else descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL)
      f = m.field.add(name=name, number=num, type=ftype, label=label)
      if type_name:
        f.type_name = type_name

  messages = message_factory.GetMessages([file_proto])
  return messages[f"{file_proto.package}.HostAgents"]


def extract_md_frontmatter(content: str) -> str:
  """Extracts raw YAML frontmatter from markdown content.

  Args:
    content: The full markdown content string.

  Returns:
    The raw YAML frontmatter string between the '---' delimiters.

  Raises:
    ValueError: If content is empty or delimiters are missing.
  """
  if not content.strip():
    raise ValueError("Markdown content is empty.")
  lines = content.splitlines()
  if lines[0].strip() != "---":
    raise ValueError("Missing starting YAML frontmatter delimiter '---'.")

  for i in range(1, len(lines)):
    if lines[i].strip() == "---":
      return "\n".join(lines[1:i])

  raise ValueError("Missing closing YAML frontmatter delimiter '---'.")


def validate_skill_reference(
    agent_id: str,
    expected_desc: str,
    skill_ref: str,
    root_path: pathlib.Path,
) -> list[str]:
  skill_path = root_path / skill_ref
  if not skill_path.is_file():
    return [f"Agent '{agent_id}': skill file does not exist: '{skill_ref}'"]

  try:
    skill_content = skill_path.read_text(encoding="utf-8")
  except (OSError, UnicodeDecodeError) as e:
    return [f"Agent '{agent_id}': could not read skill '{skill_ref}': {e}"]

  try:
    frontmatter_raw = extract_md_frontmatter(skill_content).strip()
  except ValueError as e:
    return [f"Agent '{agent_id}': skill '{skill_ref}': {e}"]

  if not frontmatter_raw:
    return [
        f"Agent '{agent_id}': skill '{skill_ref}': YAML frontmatter is empty.",
    ]

  try:
    frontmatter = yaml.safe_load(frontmatter_raw)
  except yaml.YAMLError as e:
    return [f"Agent '{agent_id}': invalid YAML in skill '{skill_ref}': {e}"]

  if not isinstance(frontmatter, dict):
    return [f"Agent '{agent_id}': skill '{skill_ref}' frontmatter not a dict."]

  errors: list[str] = []
  fm_id = str(frontmatter.get("id") or frontmatter.get("name", "")).strip()
  if agent_id != fm_id and agent_id != f"crossbench-{fm_id}":
    errors.append(f"Agent id '{agent_id}' does not match frontmatter id/name "
                  f"'{fm_id}' in '{skill_ref}'.")

  fm_desc = str(frontmatter.get("description", "")).strip()
  if fm_desc != expected_desc.strip():
    errors.append(
        f"Agent '{agent_id}': description in agent_configs.textproto does "
        f"not match description in '{skill_ref}'.")

  return errors


def validate_path_regexes(
    agent_id: str,
    filters: Sequence[Any],
    filter_kind: str,
) -> list[str]:
  errors: list[str] = []
  for f in filters:
    for regex in f.path_regex:
      try:
        re.compile(regex)
      except re.error as e:
        errors.append(f"Agent '{agent_id}': invalid {filter_kind} path_regex "
                      f"'{regex}': {e}")
  return errors


def validate_include_filters(
    agent_id: str,
    filters: Sequence[Any],
) -> list[str]:
  errors: list[str] = []
  for f in filters:
    if not f.project:
      errors.append(
          f"Agent '{agent_id}': include_filter is missing 'project' "
          f"(must explicitly specify project: '{_EXPECTED_PROJECT}' to avoid "
          "host-wide matching across other repositories).")
    elif list(f.project) != [_EXPECTED_PROJECT]:
      errors.append(
          f"Agent '{agent_id}': unexpected project in include_filter: "
          f"{list(f.project)} (expected: ['{_EXPECTED_PROJECT}']).")
  return errors


def validate_agent_config(
    config: Any,
    root_path: pathlib.Path,
) -> list[str]:
  agent_id: str = config.id
  if not agent_id:
    return ["AgentConfig is missing required 'id' field."]

  errors: list[str] = []
  if not config.skills:
    errors.append(f"Agent '{agent_id}': missing 'skills' field.")
  else:
    for skill_ref in config.skills:
      errors.extend(
          validate_skill_reference(agent_id, config.description, skill_ref,
                                   root_path))

  if not config.include_filters:
    errors.append(f"Agent '{agent_id}': missing 'include_filters' "
                  f"(agent would be disabled by CRACS).")
  else:
    errors.extend(
        validate_path_regexes(agent_id, config.include_filters, "include"))
    errors.extend(validate_include_filters(agent_id, config.include_filters))

  errors.extend(
      validate_path_regexes(agent_id, config.exclude_filters, "exclude"))

  return errors


def validate_agent_configs(
    content: str,
    root_path: pathlib.Path,
) -> list[str]:
  host_agents_class = create_host_agents_message_class()
  msg = host_agents_class()
  try:
    text_format.Parse(content, msg)
  except text_format.ParseError as e:
    return [f"Protobuf syntax error in agent_configs.textproto: {e}"]

  if not msg.configs:
    return ["No agent configs found in agent_configs.textproto."]

  errors: list[str] = []
  seen_ids: set[str] = set()

  for config in msg.configs:
    agent_id: str = config.id
    if agent_id:
      if agent_id in seen_ids:
        errors.append(f"Duplicate agent id found: '{agent_id}'")
      seen_ids.add(agent_id)
    errors.extend(validate_agent_config(config, root_path))

  return errors


class AgentConfigsTestCase(unittest.TestCase):

  def test_repo_agent_configs(self) -> None:
    repo_root = pathlib.Path(__file__).parents[2]
    config_file = repo_root / "agents" / "agent_configs.textproto"
    self.assertTrue(config_file.is_file(),
                    f"Missing config file: {config_file}")
    content = config_file.read_text(encoding="utf-8")
    errors = validate_agent_configs(content, repo_root)
    self.assertEqual(
        errors, [], "Validation errors in agents/agent_configs.textproto:\n" +
        "\n".join(errors))


class AgentConfigsValidatorMockTestCase(unittest.TestCase):

  def setUp(self) -> None:
    super().setUp()
    self.temp_dir = tempfile.TemporaryDirectory()
    self.root_path = pathlib.Path(self.temp_dir.name)
    self.skill_dir = self.root_path / "agents" / "skills" / "my-skill"
    self.skill_dir.mkdir(parents=True, exist_ok=True)
    self.skill_file = self.skill_dir / "SKILL.md"
    self.skill_file.write_text(
        "---\n"
        "name: My Skill\n"
        "id: crossbench-my-skill\n"
        "description: Validates skills.\n"
        "---\n",
        encoding="utf-8")

  def tearDown(self) -> None:
    self.temp_dir.cleanup()
    super().tearDown()

  def test_valid_agent_config(self) -> None:
    proto_text = ("configs {\n"
                  '  id: "crossbench-my-skill"\n'
                  '  display_name: "My Skill"\n'
                  '  description: "Validates skills."\n'
                  '  skills: "agents/skills/my-skill/SKILL.md"\n'
                  "  include_filters {\n"
                  '    project: "crossbench"\n'
                  '    path_regex: ".*\\\\.py$"\n'
                  "  }\n"
                  "}\n")
    errors = validate_agent_configs(proto_text, self.root_path)
    self.assertEqual(errors, [])

  def test_syntax_error(self) -> None:
    proto_text = "configs { invalid syntax\n"
    errors = validate_agent_configs(proto_text, self.root_path)
    self.assertTrue(any("syntax error" in e.lower() for e in errors))

  def test_missing_skills_file(self) -> None:
    proto_text = ("configs {\n"
                  '  id: "crossbench-my-skill"\n'
                  '  description: "Validates skills."\n'
                  '  skills: "agents/skills/nonexistent/SKILL.md"\n'
                  "  include_filters {\n"
                  '    project: "crossbench"\n'
                  '    path_regex: ".*\\\\.py$"\n'
                  "  }\n"
                  "}\n")
    errors = validate_agent_configs(proto_text, self.root_path)
    self.assertTrue(any("does not exist" in e for e in errors))

  def test_id_mismatch(self) -> None:
    proto_text = ("configs {\n"
                  '  id: "crossbench-wrong-id"\n'
                  '  description: "Validates skills."\n'
                  '  skills: "agents/skills/my-skill/SKILL.md"\n'
                  "  include_filters {\n"
                  '    project: "crossbench"\n'
                  '    path_regex: ".*\\\\.py$"\n'
                  "  }\n"
                  "}\n")
    errors = validate_agent_configs(proto_text, self.root_path)
    self.assertTrue(
        any("does not match frontmatter id/name" in e for e in errors))

  def test_description_mismatch(self) -> None:
    proto_text = ("configs {\n"
                  '  id: "crossbench-my-skill"\n'
                  '  description: "Different description."\n'
                  '  skills: "agents/skills/my-skill/SKILL.md"\n'
                  "  include_filters {\n"
                  '    project: "crossbench"\n'
                  '    path_regex: ".*\\\\.py$"\n'
                  "  }\n"
                  "}\n")
    errors = validate_agent_configs(proto_text, self.root_path)
    self.assertTrue(any("does not match description" in e for e in errors))

  def test_invalid_path_regex(self) -> None:
    proto_text = ("configs {\n"
                  '  id: "crossbench-my-skill"\n'
                  '  description: "Validates skills."\n'
                  '  skills: "agents/skills/my-skill/SKILL.md"\n'
                  "  include_filters {\n"
                  '    project: "crossbench"\n'
                  '    path_regex: "[invalid regex"\n'
                  "  }\n"
                  "}\n")
    errors = validate_agent_configs(proto_text, self.root_path)
    self.assertTrue(any("invalid include path_regex" in e for e in errors))

  def test_skill_missing_frontmatter(self) -> None:
    self.skill_file.write_text("No frontmatter here\n", encoding="utf-8")
    proto_text = ("configs {\n"
                  '  id: "crossbench-my-skill"\n'
                  '  description: "Validates skills."\n'
                  '  skills: "agents/skills/my-skill/SKILL.md"\n'
                  "  include_filters {\n"
                  '    project: "crossbench"\n'
                  '    path_regex: ".*\\\\.py$"\n'
                  "  }\n"
                  "}\n")
    errors = validate_agent_configs(proto_text, self.root_path)
    self.assertTrue(
        any("Missing starting YAML frontmatter delimiter" in e for e in errors))

  def test_skill_empty_frontmatter(self) -> None:
    self.skill_file.write_text("---\n---\n", encoding="utf-8")
    proto_text = ("configs {\n"
                  '  id: "crossbench-my-skill"\n'
                  '  description: "Validates skills."\n'
                  '  skills: "agents/skills/my-skill/SKILL.md"\n'
                  "  include_filters {\n"
                  '    project: "crossbench"\n'
                  '    path_regex: ".*\\\\.py$"\n'
                  "  }\n"
                  "}\n")
    errors = validate_agent_configs(proto_text, self.root_path)
    self.assertTrue(any("YAML frontmatter is empty" in e for e in errors))

  def test_duplicate_agent_id(self) -> None:
    proto_text = ("configs {\n"
                  '  id: "crossbench-my-skill"\n'
                  '  description: "Validates skills."\n'
                  '  skills: "agents/skills/my-skill/SKILL.md"\n'
                  "  include_filters {\n"
                  '    project: "crossbench"\n'
                  '    path_regex: ".*\\\\.py$"\n'
                  "  }\n"
                  "}\n"
                  "configs {\n"
                  '  id: "crossbench-my-skill"\n'
                  '  description: "Validates skills."\n'
                  '  skills: "agents/skills/my-skill/SKILL.md"\n'
                  "  include_filters {\n"
                  '    project: "crossbench"\n'
                  '    path_regex: ".*\\\\.py$"\n'
                  "  }\n"
                  "}\n")
    errors = validate_agent_configs(proto_text, self.root_path)
    self.assertTrue(any("Duplicate agent id found" in e for e in errors))

  def test_missing_project_in_include_filter(self) -> None:
    proto_text = ("configs {\n"
                  '  id: "crossbench-my-skill"\n'
                  '  display_name: "My Skill"\n'
                  '  description: "Validates skills."\n'
                  '  skills: "agents/skills/my-skill/SKILL.md"\n'
                  "  include_filters {\n"
                  '    path_regex: ".*\\\\.py$"\n'
                  "  }\n"
                  "}\n")
    errors = validate_agent_configs(proto_text, self.root_path)
    self.assertTrue(any("missing 'project'" in e for e in errors))

  def test_invalid_project_in_include_filter(self) -> None:
    proto_text = ("configs {\n"
                  '  id: "crossbench-my-skill"\n'
                  '  display_name: "My Skill"\n'
                  '  description: "Validates skills."\n'
                  '  skills: "agents/skills/my-skill/SKILL.md"\n'
                  "  include_filters {\n"
                  '    project: "other-project"\n'
                  '    path_regex: ".*\\\\.py$"\n'
                  "  }\n"
                  "}\n")
    errors = validate_agent_configs(proto_text, self.root_path)
    self.assertTrue(
        any("unexpected project in include_filter" in e for e in errors))

  def test_extract_md_frontmatter_valid(self) -> None:
    content = ("---\n"
               "name: test-skill\n"
               "description: A test skill description.\n"
               "---\n"
               "\n"
               "# Content\n")
    self.assertEqual(
        extract_md_frontmatter(content),
        "name: test-skill\ndescription: A test skill description.")

  def test_extract_md_frontmatter_empty(self) -> None:
    with self.assertRaises(ValueError) as cm:
      extract_md_frontmatter("")
    self.assertIn("Markdown content is empty.", str(cm.exception))

  def test_extract_md_frontmatter_missing_start_delimiter(self) -> None:
    content = "name: test\n---\n"
    with self.assertRaises(ValueError) as cm:
      extract_md_frontmatter(content)
    self.assertIn("Missing starting YAML frontmatter delimiter '---'.",
                  str(cm.exception))

  def test_extract_md_frontmatter_missing_end_delimiter(self) -> None:
    content = "---\nname: test\ndescription: desc\n"
    with self.assertRaises(ValueError) as cm:
      extract_md_frontmatter(content)
    self.assertIn("Missing closing YAML frontmatter delimiter '---'.",
                  str(cm.exception))


if __name__ == "__main__":
  test_helper.run_pytest(__file__)
