/* =========================================================
   chat.js — 聊天流程
   负责「一条消息从发出到上屏」的编排：渲染气泡、翻历史、发消息、接流式回复。
   只管聊天这一件事；界面细节调 ui.js，网络细节调 api.js。
   ========================================================= */

import { state } from "./state.js";
import { fetchHistory, streamChat } from "./api.js";
import * as ui from "./ui.js";

/** 创建一条消息节点；role 取 "user" 或 "ai"，只决定样式不影响内容。 */
export function makeMessage(role, text) {
    const node = document.createElement("div");
    node.className = "msg " + role;
    node.textContent = text;
    return node;
}

/** 追加一条消息到列表末尾并滚到底部，返回该节点（流式回复要拿它不断改内容）。 */
export function addMessage(role, text) {
    const node = makeMessage(role, text);
    ui.el.messages.appendChild(node);
    ui.el.output.scrollTop = ui.el.output.scrollHeight;
    return node;
}

/**
 * 加载最新一页历史。
 * 没有任何历史时展示欢迎页；401 说明登录态过期，直接回登录页。
 */
export async function loadInitialHistory() {
    try {
        const data = await fetchHistory(null);

        if (!data.items.length) {
            ui.showWelcome();
            return;
        }

        ui.el.messages.innerHTML = "";
        for (const item of data.items) {
            ui.el.messages.appendChild(
                makeMessage(item.role === "user" ? "user" : "ai", item.content)
            );
        }
        ui.showMessages();
        ui.el.output.scrollTop = ui.el.output.scrollHeight;

        state.historyBefore = data.next_before_id;
        state.hasMoreHistory = data.has_more;
    } catch (e) {
        if (e.code === 401) {
            ui.showAuth();
            return;
        }
        ui.showWelcome();
    }
}

/**
 * 向上翻一页历史。
 * 插入旧消息会让内容变高，所以插入后用高度差把 scrollTop 顶回去，
 * 用户眼前的画面才不会突然跳走。
 */
export async function loadOlderHistory() {
    if (state.loadingHistory || !state.hasMoreHistory || !state.historyBefore) return;

    state.loadingHistory = true;
    const prevHeight = ui.el.messages.scrollHeight;

    try {
        const data = await fetchHistory(state.historyBefore);

        const frag = document.createDocumentFragment();
        for (const item of data.items) {
            frag.appendChild(
                makeMessage(item.role === "user" ? "user" : "ai", item.content)
            );
        }
        ui.el.messages.insertBefore(frag, ui.el.messages.firstChild);
        ui.el.output.scrollTop += ui.el.messages.scrollHeight - prevHeight;

        state.historyBefore = data.next_before_id;
        state.hasMoreHistory = data.has_more;
    } catch (e) {
        if (e.code === 401) {
            ui.showAuth();
            return;
        }
        console.error("加载更早消息失败", e);
    } finally {
        state.loadingHistory = false;
    }
}

/**
 * 发送一条消息。
 * 顺序：清空输入框 → 用户气泡上屏 → 占位气泡显示三点动画 →
 *       流式增量写进同一个气泡 → 出错时把原因写进气泡。
 */
export async function sendMessage(text) {
    ui.el.msgInput.value = "";
    ui.autoGrow();
    ui.updateSendState();

    ui.showMessages();
    ui.scrollToLatest(ui.el.messages);

    addMessage("user", text);

    const bubble = addMessage("ai", "");
    bubble.classList.add("typing");
    bubble.innerHTML = '<span class="dots"><span></span><span></span><span></span></span>';
    ui.scrollToLatest(bubble);

    let started = false;

    await streamChat(text, {
        onUnauthorized: () => ui.showAuth(),

        onError: (message) => {
            bubble.classList.remove("typing");
            bubble.textContent = message;
        },

        onDelta: (_chunk, full) => {
            // 第一个增量到达时才撤掉等待动画，避免闪一下空白
            if (!started) {
                started = true;
                bubble.classList.remove("typing");
            }
            bubble.textContent = full;
            ui.scrollToLatest(bubble);
        },
    });
}
