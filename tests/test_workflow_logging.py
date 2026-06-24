from productv2.workflow_logging import WorkflowRunLogger
from productv2.workflow_logging import extract_decisions
from productv2.workflow_logging import wrap_node_with_logging


def test_workflow_logger_writes_chinese_log_events(tmp_path) -> None:
    logger = WorkflowRunLogger(tmp_path, run_id="run-test")

    logger.write("custom", node="node-a", data={"status": "ok"})

    log_text = logger.path.read_text(encoding="utf-8")
    assert logger.path.name == "run-test.log"
    assert "工作流运行日志" in log_text
    assert "运行编号：run-test" in log_text
    assert "事件：custom" in log_text
    assert "逻辑单元：node-a" in log_text
    assert "- status: ok" in log_text


def test_wrap_node_with_logging_records_input_output_and_decisions(tmp_path) -> None:
    logger = WorkflowRunLogger(tmp_path, run_id="run-node")

    def node(state):
        return {"size_reference_result": {"status": "ok", "reason": "有参照"}}

    wrapped = wrap_node_with_logging("detect_size_reference", node, logger)

    output = wrapped({"main_image_result": {"status": "ok"}})

    assert output["size_reference_result"]["status"] == "ok"
    log_text = logger.path.read_text(encoding="utf-8")
    assert "事件：逻辑单元开始" in log_text
    assert "事件：逻辑单元结束" in log_text
    assert "逻辑单元：detect_size_reference" in log_text
    assert "- 输入数据 (input):" in log_text
    assert "- main_image_result:" in log_text
    assert "- status: ok" in log_text
    assert "- 输出数据 (output):" in log_text
    assert "- reason: 有参照" in log_text
    assert "- 状态记忆摘要 (summary):" in log_text
    assert "- 判断结果 (decisions):" in log_text
    assert "- size_reference_result.reason: 有参照" in log_text


def test_workflow_logger_renames_file_with_product_name(tmp_path) -> None:
    logger = WorkflowRunLogger(tmp_path, run_id="run-product")
    original_path = logger.path

    renamed_path = logger.rename_for_product(
        product_name='Cool / Necklace: "Pearl"*',
        platform="1688",
        product_id="p/1",
    )

    assert renamed_path.name == "Cool - Necklace- -Pearl-__1688__p-1.log"
    assert not original_path.exists()
    assert renamed_path.exists()
    log_text = renamed_path.read_text(encoding="utf-8")
    assert "事件：日志文件重命名" in log_text
    assert "- 产品名称 (product_name): Cool / Necklace: \"Pearl\"*" in log_text


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
