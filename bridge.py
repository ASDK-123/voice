from flask import Flask, request, Response, jsonify
import requests
import threading
import sys
import uuid

# ================= 配置区域 =================
COSYVOICE_URL = "http://127.0.0.1:9880"
# ===========================================

app = Flask(__name__)

# 全局锁：真正的线程锁
# 确保同一时间只有一个请求能通过
PROCESS_LOCK = threading.Lock()

print(f"[Bridge] Flask 桥接服务启动 (同步多线程模式) -> {COSYVOICE_URL}")

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
    print(f"[Bridge] 线程 {threading.get_ident()} 等待获取锁...")
    PROCESS_LOCK.acquire()
    print(f"[Bridge] 线程 {threading.get_ident()} 已获取锁，开始处理")
    
    try:
        data = request.get_json()
        if not data:
            if PROCESS_LOCK.locked(): PROCESS_LOCK.release()
            return jsonify({"error": "No JSON data"}), 400
            
        input_text = data.get("input", "")
        voice_name = data.get("voice", "胡桃")
        
        import time
        print(f"[IN] [{time.strftime('%H:%M:%S')}] 收到请求: Len={len(input_text)} | Voice={voice_name} | Text={input_text[:50]}...")

        speed = data.get("speed", 1.0) or 1.0
        try:
            speed = float(speed)
        except Exception:
            speed = 1.0

        req_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:16]}"
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
            print(f"[ERROR] 连接后端失败: {e}")
            if PROCESS_LOCK.locked(): PROCESS_LOCK.release()
            return jsonify({"error": str(e)}), 502

        if resp.status_code != 200:
            print(f"[ERROR] 后端拒绝: {resp.status_code} - {resp.text}")
            if PROCESS_LOCK.locked(): PROCESS_LOCK.release()
            return jsonify({"error": resp.text}), resp.status_code

        print(f"[OK] 开始流式传输...")

        # 3. 定义流生成器（负责释放锁）
        def generate():
            try:
                for chunk in resp.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
            except Exception as e:
                print(f"[ERROR] 流传输异常: {e}")
            finally:
                resp.close()
                # 【核心】：在生成器结束时释放锁
                # 无论流传输成功还是网络中断，都会执行这里
                if PROCESS_LOCK.locked():
                    PROCESS_LOCK.release()
                    print(f"[Bridge] 锁已释放 (线程 {threading.get_ident()})")

        return Response(generate(), mimetype='audio/wav')

    except Exception as e:
        print(f"[ERROR] 全局异常: {e}")
        # 兜底释放锁
        if PROCESS_LOCK.locked():
            PROCESS_LOCK.release()
            print("[Bridge] 异常释放锁")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # threaded=True 是 Flask 默认行为，为了明确起见显式开启
    app.run(host="0.0.0.0", port=5000, threaded=True)
