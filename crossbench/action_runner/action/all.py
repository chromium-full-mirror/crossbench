# Copyright 2024 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from crossbench.action_runner.action.action import ACTIONS, Action
from crossbench.action_runner.action.clear_cache import ClearCacheAction
from crossbench.action_runner.action.click import ClickAction
from crossbench.action_runner.action.close_all_apps import CloseAllAppsAction
from crossbench.action_runner.action.close_all_tabs import CloseAllTabsAction
from crossbench.action_runner.action.close_app import CloseAppAction
from crossbench.action_runner.action.close_tab import CloseTabAction
from crossbench.action_runner.action.dump_html import DumpHtmlAction
from crossbench.action_runner.action.get import GetAction
from crossbench.action_runner.action.inject_new_document_script import \
    InjectNewDocumentScriptAction
from crossbench.action_runner.action.js import JsAction
from crossbench.action_runner.action.launch_app import LaunchAppAction
from crossbench.action_runner.action.meet_create import MeetCreateAction
from crossbench.action_runner.action.meet_script import MeetScriptAction
from crossbench.action_runner.action.meminfo import MeminfoAction
from crossbench.action_runner.action.mouse_move import MouseMoveAction
from crossbench.action_runner.action.open_devtools import OpenDevToolsAction
from crossbench.action_runner.action.probe import ProbeAction
from crossbench.action_runner.action.raw_input import RawInputAction
from crossbench.action_runner.action.screenshot import ScreenshotAction
from crossbench.action_runner.action.scroll import ScrollAction
from crossbench.action_runner.action.start_browser import StartBrowserAction
from crossbench.action_runner.action.stop_browser import StopBrowserAction
from crossbench.action_runner.action.swipe import SwipeAction
from crossbench.action_runner.action.switch_frame import SwitchFrameAction
from crossbench.action_runner.action.switch_tab import SwitchTabAction
from crossbench.action_runner.action.text_input import TextInputAction
from crossbench.action_runner.action.wait import WaitAction
from crossbench.action_runner.action.wait_for_condition import \
    WaitForConditionAction
from crossbench.action_runner.action.wait_for_download import \
    WaitForDownloadAction
from crossbench.action_runner.action.wait_for_element import \
    WaitForElementAction
from crossbench.action_runner.action.wait_for_ready_state import \
    WaitForReadyStateAction
from crossbench.action_runner.action.wait_for_url_matches import \
    WaitForUrlMatchesAction

ACTIONS_TUPLE: tuple[type[Action], ...] = (
    ClearCacheAction,
    ClickAction,
    CloseAllAppsAction,
    CloseAppAction,
    CloseTabAction,
    CloseAllTabsAction,
    DumpHtmlAction,
    GetAction,
    InjectNewDocumentScriptAction,
    JsAction,
    LaunchAppAction,
    MeetCreateAction,
    MeetScriptAction,
    MeminfoAction,
    MouseMoveAction,
    ProbeAction,
    RawInputAction,
    OpenDevToolsAction,
    ScreenshotAction,
    ScrollAction,
    StartBrowserAction,
    StopBrowserAction,
    SwipeAction,
    SwitchTabAction,
    SwitchFrameAction,
    TextInputAction,
    WaitAction,
    WaitForConditionAction,
    WaitForDownloadAction,
    WaitForElementAction,
    WaitForReadyStateAction,
    WaitForUrlMatchesAction,
)
for action_cls in ACTIONS_TUPLE:
  ACTIONS[action_cls.TYPE] = action_cls

assert len(ACTIONS_TUPLE) == len(ACTIONS), "Non unique Action.TYPE present"
