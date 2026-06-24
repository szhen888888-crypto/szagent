import json

from productv2.workflow_logging import WorkflowRunLogger
from productv2.workflow_logging import extract_decisions
from productv2.workflow_logging import wrap_node_with_logging


def test_workflow_logger_writes_jsonl_events(tmp_path) -> None:
    logger = WorkflowRunLogger(tmp_path, run_id="run-test")

    logger.write("custom", node="node-a", data={"status": "ok"})

    lines = logger.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["run_id"] == "run-test"
    assert event["event"] == "custom"
    assert event["node"] == "node-a"
    assert event["data"] == {"status": "ok"}


def test_wrap_node_with_logging_records_input_output_and_decisions(tmp_path) -> None:
    logger = WorkflowRunLogger(tmp_path, run_id="run-node")

    def node(state):
        return {"size_reference_result": {"status": "ok", "reason": "有参照"}}

    wrapped = wrap_node_with_logging("detect_size_reference", node, logger)

    output = wrapped({"main_image_result": {"status": "ok"}})

    assert output["size_reference_result"]["status"] == "ok"
    events = [
        json.loads(line)
        for line in logger.path.read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event"] for event in events] == ["node_start", "node_end"]
    assert events[0]["data"]["input"]["main_image_result"]["status"] == "ok"
    assert events[1]["data"]["output"]["size_reference_result"]["reason"] == "有参照"
    assert events[1]["data"]["decisions"] == {
        "size_reference_result.status": "ok",
        "size_reference_result.reason": "有参照",
    }


def test_extract_decisions_collects_nested_result_flags() -> None:
    decisions = extract_decisions(
        {
            "enroute_analysis_result": {
                "status": "ok",
                "cache": "hit",
                "reference_image_path": "/tmp/02.jpg",
                "analysis": {
                    "selected_model_profile": {"profile_key": "vintage_muse"}
                },
            }
        }
    )

    assert decisions["enroute_analysis_result.status"] == "ok"
    assert decisions["enroute_analysis_result.cache"] == "hit"
    assert decisions["enroute_analysis_result.reference_image_path"] == "/tmp/02.jpg"
    assert decisions[
        "enroute_analysis_result.analysis.selected_model_profile"
    ] == {"profile_key": "vintage_muse"}
