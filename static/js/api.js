/* =========================================================
   api.js — 与后端的唯一出口
   只负责「怎么请求、怎么解析」，不碰界面。
   结果或错误交回调用方（chat.js / ui.js / main.js）决定怎么展示。
   ========================================================= */

import { state, clearAuth } from "./state.js";

/** 登录态的请求头；未登录时返回空对象，便于直接展开合并。 */
export function authHeaders() {
    return state.token ? { Authorization: "Bearer " + state.token } : {};
}

/** 用户自备 API Key 的请求头；未配置时返回空对象。 */
export function apiKeyHeaders() {
    return state.apiKey ? { "X-API-Key": state.apiKey } : {};
}

/**
 * 统一的 JSON 请求封装。
 * 返回 { ok, status, data }，把「HTTP 是否成功」和「业务怎么处理」分开，
 * 调用方不用每次都写 res.json().catch(...)。
 */
async function requestJSON(path, { method = "POST", body, extraHeaders = {} } = {}) {
    const headers = {
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...authHeaders(),
        ...extraHeaders,
    };
    const res = await fetch(path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
}

/** 登录，成功后拿到 access_token。 */
export async function login(username, password) {
    return requestJSON("/login", { body: { username, password } });
}

/** 注册新账号；后端不会自动登录，仍要再走一次登录。 */
export async function register(username, password) {
    return requestJSON("/register", { body: { username, password } });
}

/**
 * 拉取一页历史消息。
 * beforeId 为空表示最新一页；401 时顺手清掉本地登录态，并抛出 code=401 供上层跳登录页。
 */
export async function fetchHistory(beforeId, limit = 30) {
    const result = await requestJSON("/history", { body: { before_id: beforeId, limit } });
    if (result.status === 401) {
        clearAuth();
        throw Object.assign(new Error("unauthorized"), { code: 401 });
    }
    if (!result.ok) throw new Error("history failed");
    return result.data;   // { items, next_before_id, has_more }
}

/** 校验用户填写的 API Key 是否可用，返回 { ok, message }。 */
export async function testApiKey(key) {
    const result = await requestJSON("/api-key/test", { extraHeaders: { "X-API-Key": key } });
    return {
        ok: result.ok && !!result.data.ok,
        message: result.data.message || (result.ok ? "连接成功" : "测试失败"),
    };
}

/**
 * 拉取记忆大脑数据：常驻画像 + 所有已关闭的记忆片段。
 * 401 表示登录态失效，清掉本地 token 并抛出 code=401，由页面引导重新登录。
 */
export async function fetchMemoryGraph() {
    const result = await requestJSON("/memory/graph", { method: "GET" });
    if (result.status === 401) {
        clearAuth();
        throw Object.assign(new Error("unauthorized"), { code: 401 });
    }
    if (!result.ok) throw new Error("memory failed");
    return result.data;   // { profile, segments, stats }
}

/**
 * 发送一条消息并消费 SSE 流。
 * handlers 需提供 onDelta(chunk, full) / onError(message) / onUnauthorized()。
 * 出错时也把「已收到的内容」保留在界面上，不让气球突然变空。
 */
export async function streamChat(message, { onDelta, onError, onUnauthorized }) {
    let res;
    try {
        res = await fetch("/chat/stream", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                ...authHeaders(),
                ...apiKeyHeaders(),
            },
            body: JSON.stringify({ message }),
        });
    } catch (e) {
        onError("网络错误");
        return;
    }

    if (res.status === 401) {
        clearAuth();
        onUnauthorized();
        return;
    }
    if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        onError("出错了 - " + (typeof data.detail === "string" ? data.detail : res.status));
        return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let full = "";

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        // SSE 以空行分隔事件，最后一段可能不完整，留在 buffer 里等下一次
        const parts = buffer.split("\n\n");
        buffer = parts.pop();

        for (const part of parts) {
            if (!part.startsWith("data: ")) continue;
            const content = part.slice(6);

            if (content.startsWith("[START]")) continue;   // 服务端开流的占位事件
            if (content === "[DONE]") return;              // 正常结束
            if (content.startsWith("[ERROR]")) {
                onError("出错了 - " + content.replace("[ERROR]", "").trim());
                return;
            }
            if (content === "") continue;

            full += content;
            onDelta(content, full);
        }
    }
}
