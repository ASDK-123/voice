from flask import Flask, request, Response, jsonify
import requests
import threading
import sys
import uuid
from core.logging import emit_event, get_logger, init_logging, install_crash_handlers

# ================= 配置区域 =================
COSYVOICE_URL = "http://127.0.0.1:9880"
# ===========================================

app = Flask(__name__)
init_logging()
install_crash_handlers()
logger = get_logger("bridge")

# 全局锁：真正的线程锁
# 确保同一时间只有一个请求能通过
PROCESS_LOCK = threading.Lock()

emit_event(
    logger=logger,
    level="INFO",
    module="bridge",
    event="BRG_START",
    msg_zh="Bridge 服务启动",
    fields={"target": COSYVOICE_URL},
)

@app.route('/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({
        "status": "ok",
        "locked": PROCESS_LOCK.locked(),
        "mode": "flask_threading_sync"
    })

@app.route('/v1/audio/speech', methods=['POST'])
def openai_to_cosyvoice():
    # 1. 手动获取锁（阻塞等待）
    logger.info(f"[INFO] 线程 {threading.get_ident()} 等待获取锁...")
    PROCESS_LOCK.acquire()
    logger.info(f"[INFO] 线程 {threading.get_ident()} 已获取锁，开始处理")
    
    try:
        data = request.get_json()
        if not data:
            if PROCESS_LOCK.locked(): PROCESS_LOCK.release()
            return jsonify({"error": "No JSON data"}), 400
            
        input_text = data.get("input", "")
        voice_name = data.get("voice", "胡桃")
        
        import time
        req_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:16]}"
        emit_event(
            logger=logger,
            level="INFO",
            module="bridge",
            event="API_REQ_START",
            request_id=req_id,
            msg_zh="Bridge 收到语音请求",
            fields={"method": "POST", "path": "/v1/audio/speech", "voice_id": voice_name, "text_len": len(input_text)},
        )

        speed = data.get("speed", 1.0) or 1.0
        try:
            speed = float(speed)
        except Exception:
            speed = 1.0

        headers = {"X-Request-Id": req_id}

        payload = {
            "text": input_text,
            "voice_id": voice_name,
            "speed": speed,
            "response_format": "audio"
        }

        # 2. 发送同步请求
        try:
            # 建立连接
            v2_url = COSYVOICE_URL.rstrip("/") + "/api/v2/synthesize"
            resp = requests.post(v2_url, json=payload, headers=headers, stream=True, timeout=120)
        except Exception as e:
            emit_event(
                logger=logger,
                level="ERROR",
                module="bridge",
                event="API_REQ_FAIL",
                request_id=req_id,
                msg_zh="Bridge 连接后端失败",
                fields={"method": "POST", "path": "/api/v2/synthesize", "status": 502, "error_code": "bridge_upstream_connect_error", "reason": str(e)},
            )
            if PROCESS_LOCK.locked(): PROCESS_LOCK.release()
            return jsonify({"error": str(e)}), 502

        if resp.status_code != 200:
            emit_event(
                logger=logger,
                level="ERROR",
                module="bridge",
                event="API_REQ_FAIL",
                request_id=req_id,
                msg_zh="Bridge 上游返回错误",
                fields={"method": "POST", "path": "/api/v2/synthesize", "status": int(resp.status_code), "error_code": "bridge_upstream_http_error"},
            )
            if PROCESS_LOCK.locked(): PROCESS_LOCK.release()
            return jsonify({"error": resp.text}), resp.status_code

        emit_event(
            logger=logger,
            level="INFO",
            module="bridge",
            event="API_REQ_END",
            request_id=req_id,
            msg_zh="Bridge 请求上游成功，开始传输音频流",
            fields={"method": "POST", "path": "/api/v2/synthesize", "status": 200, "duration_ms": 0},
        )

        # 3. 定义流生成器（负责释放锁）
        def generate():
            try:
                for chunk in resp.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
            except Exception as e:
                emit_event(
                    logger=logger,
                    level="ERROR",
                    module="bridge",
                    event="BRG_STREAM_FAIL",
                    request_id=req_id,
                    msg_zh="Bridge 音频流传输异常",
                    fields={"reason": str(e)},
                )
            finally:
                resp.close()
                # 【核心】：在生成器结束时释放锁
                # 无论流传输成功还是网络中断，都会执行这里
                if PROCESS_LOCK.locked():
                    PROCESS_LOCK.release()
                    logger.info(f"[INFO] 锁已释放 (线程 {threading.get_ident()})")

        return Response(generate(), mimetype='audio/wav')

    except Exception as e:
        emit_event(
            logger=logger,
            level="ERROR",
            module="bridge",
            event="CRH_UNCAUGHT",
            msg_zh="Bridge 处理请求时发生未处理异常",
            fields={"error_type": type(e).__name__, "message": str(e)},
        )
        # 兜底释放锁
        if PROCESS_LOCK.locked():
            PROCESS_LOCK.release()
            logger.warning("[WARN] 异常释放锁")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # threaded=True 是 Flask 默认行为，为了明确起见显式开启
    app.run(host="0.0.0.0", port=5000, threaded=True)
