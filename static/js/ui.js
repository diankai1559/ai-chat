/* =========================================================
   ui.js — 视图与交互
   负责「谁显示、谁隐藏、谁在动」：元素查找、视图切换、弹窗、
   手机键盘适配、滚动位置、输入框高度。
   不发业务请求（请求都在 api.js），也不编排聊天流程（在 chat.js / main.js）。
   ========================================================= */

import { state, clearAuth, saveApiKey } from "./state.js";
import { testApiKey } from "./api.js";

/** 页面元素统一在这里取一次，避免各模块各自 querySelector 写错 id。 */
export const el = {
    // 登录 / 注册
    authView: document.getElementById("auth-view"),
    tabLogin: document.getElementById("tab-login"),
    tabRegister: document.getElementById("tab-register"),
    authTitle: document.getElementById("auth-title"),
    authSub: document.getElementById("auth-sub"),
    authSubmit: document.getElementById("auth-submit"),
    authMsg: document.getElementById("auth-msg"),
    confirmField: document.getElementById("confirm-field"),
    usernameInput: document.getElementById("auth-username"),
    passwordInput: document.getElementById("auth-password"),
    confirmInput: document.getElementById("auth-confirm"),

    // 聊天主体
    app: document.getElementById("app"),
    output: document.getElementById("output"),
    welcome: document.getElementById("welcome"),
    messages: document.getElementById("messages"),
    msgInput: document.getElementById("msg"),
    sendBtn: document.getElementById("send"),
    title: document.getElementById("chat-title"),

    // 右上角用户菜单
    userName: document.getElementById("user-name"),
    userMenuBtn: document.getElementById("user-menu-btn"),
    userMenu: document.getElementById("user-menu"),
    menuBrain: document.getElementById("menu-brain"),
    menuConfig: document.getElementById("menu-config"),
    menuLogout: document.getElementById("menu-logout"),

    // API Key 弹窗
    apiKeyChip: document.getElementById("api-key-chip"),
    apiKeyModal: document.getElementById("api-key-modal"),
    apiKeyInput: document.getElementById("api-key-input"),
    apiKeySave: document.getElementById("api-key-save"),
    apiKeyCancel: document.getElementById("api-key-cancel"),
    apiKeyTest: document.getElementById("api-key-test"),
    apiKeyStatus: document.getElementById("api-key-status"),
};

/* ==================== 登录 / 应用视图 ==================== */

/** 显示登录页，同时清掉本地登录态。 */
export function showAuth() {
    clearAuth();
    el.app.hidden = true;
    el.authView.hidden = false;
    setTimeout(() => el.usernameInput.focus(), 0);
}

/** 隐藏登录页，进入聊天界面。 */
export function hideAuth() {
    el.authView.hidden = true;
    el.app.hidden = false;
}

/** 切换登录 / 注册：按钮高亮、标题文案、确认密码框的显隐一起改。 */
export function setAuthMode(mode) {
    state.authMode = mode;
    const isLogin = mode === "login";

    el.tabLogin.classList.toggle("active", isLogin);
    el.tabRegister.classList.toggle("active", !isLogin);
    el.confirmField.hidden = isLogin;
    el.authTitle.textContent = isLogin ? "欢迎回来" : "创建账号";
    el.authSub.textContent = isLogin ? "登录后开始对话" : "注册一个新账号";
    el.authSubmit.textContent = isLogin ? "登录" : "注册";
    el.passwordInput.setAttribute("autocomplete", isLogin ? "current-password" : "new-password");
    el.authMsg.textContent = "";
    el.usernameInput.focus();
}

/** 清空登录表单的三个输入框（密码不上屏，也不留在内存里）。 */
export function clearAuthFields() {
    el.usernameInput.value = "";
    el.passwordInput.value = "";
    el.confirmInput.value = "";
}

/* ==================== 消息区视图 ==================== */

/** 回到欢迎页，并清掉已渲染的消息节点。 */
export function showWelcome() {
    el.messages.innerHTML = "";
    el.messages.hidden = true;
    el.welcome.hidden = false;
    el.output.scrollTop = 0;
    el.title.textContent = "小满";
}

/** 切到消息列表；桌面端顺便聚焦输入框，手机端不抢焦点以免键盘弹起。 */
export function showMessages() {
    el.welcome.hidden = true;
    el.messages.hidden = false;
    if (window.matchMedia("(pointer: fine)").matches) el.msgInput.focus();
}

/**
 * 把滚动位置推到最新内容。
 * anchor 是刚插入的那条消息，用于抵消它在容器顶部之外的高度，
 * 保证流式增长时视线一直跟着最后一行，而不是来回跳。
 */
export function scrollToLatest(anchor) {
    el.output.scrollTop = el.output.scrollHeight;
    if (!anchor) return;

    const outputTop = el.output.getBoundingClientRect().top;
    const anchorTop = anchor.getBoundingClientRect().top;
    if (anchorTop < outputTop) {
        el.output.scrollTop -= (outputTop - anchorTop);
    }
}

/* ==================== 输入框 ==================== */

/** 输入框随内容自动增高，最多 200px，超过后内部滚动。 */
export function autoGrow() {
    el.msgInput.style.height = "auto";
    el.msgInput.style.height = Math.min(el.msgInput.scrollHeight, 200) + "px";
}

/** 输入框为空时禁用发送按钮。 */
export function updateSendState() {
    el.sendBtn.disabled = el.msgInput.value.trim().length === 0;
}

/* ==================== 手机键盘与视口 ==================== */

/** 消息区是否贴在底部（留 48px 容差，避免滚动惯性误判）。 */
export function isNearBottom() {
    return el.output.scrollHeight - el.output.scrollTop - el.output.clientHeight < 48;
}

/** 在 duration 毫秒内持续把消息区贴到底部，用来跟住键盘弹出/收起的动画过程。 */
export function keepPinned(duration) {
    const end = performance.now() + duration;
    const step = () => {
        el.output.scrollTop = el.output.scrollHeight;
        if (performance.now() < end) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
}

/**
 * 读取 visualViewport 算出键盘占掉的高度，写进 CSS 变量 --kb。
 * 只做「量」和「写变量」，真正的位移由 layout.css 的 padding-bottom + transition 完成。
 */
export function syncViewport() {
    const vv = window.visualViewport;
    const keyboard = vv ? Math.max(0, window.innerHeight - vv.height) : 0;
    document.documentElement.style.setProperty("--kb", keyboard + "px");
    // 用户原本就在底部时才跟着上移；已经上翻看旧消息就保持原位
    if (state.pinnedToBottom) keepPinned(keyboard > 0 ? 340 : 240);
}

/* ==================== API Key 弹窗 ==================== */

/** 清空弹窗里的状态提示，并把颜色类复位。 */
function clearApiKeyStatus() {
    el.apiKeyStatus.textContent = "";
    el.apiKeyStatus.className = "modal-status";
}

/** 已配置 API Key 时按钮加小圆点，让人知道当前用的是自己的 Key。 */
export function refreshApiKeyChip() {
    el.apiKeyChip.classList.toggle("configured", !!state.apiKey);
}

/** 打开弹窗，并把已保存的 Key 回填到输入框。 */
function openApiKeyModal() {
    el.apiKeyInput.value = state.apiKey;
    clearApiKeyStatus();
    el.apiKeyModal.hidden = false;
    setTimeout(() => el.apiKeyInput.focus(), 0);
}

/** 关闭弹窗，不保存任何改动。 */
function closeApiKeyModal() {
    el.apiKeyModal.hidden = true;
}

/** 用当前输入框里的 Key 打一次极小请求，把结果写进弹窗提示。 */
async function handleApiKeyTest() {
    const value = el.apiKeyInput.value.trim();
    if (!value) {
        el.apiKeyStatus.textContent = "请先输入 API Key";
        el.apiKeyStatus.className = "modal-status err";
        return;
    }

    el.apiKeyTest.disabled = true;
    el.apiKeyStatus.textContent = "测试中…";
    el.apiKeyStatus.className = "modal-status";
    try {
        const result = await testApiKey(value);
        el.apiKeyStatus.textContent = result.message;
        el.apiKeyStatus.className = "modal-status " + (result.ok ? "ok" : "err");
    } catch (e) {
        el.apiKeyStatus.textContent = "网络错误，请稍后重试";
        el.apiKeyStatus.className = "modal-status err";
    } finally {
        el.apiKeyTest.disabled = false;
    }
}

/** 保存输入框里的 Key 到本地，并同步按钮上的小圆点。 */
function handleApiKeySave() {
    const value = el.apiKeyInput.value.trim();
    if (!value) {
        el.apiKeyInput.focus();
        return;
    }
    saveApiKey(value);
    refreshApiKeyChip();
    closeApiKeyModal();
}

/* ==================== 全局交互绑定 ==================== */

/**
 * 绑定那些「整页通用」的交互：
 * 1) API Key 弹窗的打开/关闭/测试/保存
 * 2) 视口变化（键盘弹出）时更新 --kb
 * 3) 滚动时记录是否贴底
 * 4) 点击非可选中区域时清掉文本选区（body 是 user-select:none，浏览器不会自动清）
 */
export function initUi() {
    el.apiKeyChip.addEventListener("click", openApiKeyModal);
    el.apiKeyCancel.addEventListener("click", closeApiKeyModal);
    el.apiKeyModal.addEventListener("click", (e) => {
        if (e.target === el.apiKeyModal) closeApiKeyModal();
    });
    el.apiKeyTest.addEventListener("click", handleApiKeyTest);
    el.apiKeySave.addEventListener("click", handleApiKeySave);
    el.apiKeyInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            handleApiKeySave();
        }
        if (e.key === "Escape") closeApiKeyModal();
    });

    el.output.addEventListener("scroll", () => {
        state.pinnedToBottom = isNearBottom();
    }, { passive: true });

    // 点进输入框时先记下当前位置，键盘弹出后据此决定要不要跟着滚
    el.msgInput.addEventListener("focus", () => {
        state.pinnedToBottom = isNearBottom();
    });

    if (window.visualViewport) {
        let pending = 0;
        const schedule = () => {
            if (pending) return;
            pending = requestAnimationFrame(() => {
                pending = 0;
                syncViewport();
            });
        };
        window.visualViewport.addEventListener("resize", schedule);
        window.visualViewport.addEventListener("scroll", schedule);
        window.addEventListener("resize", schedule);
    }

    document.addEventListener("mousedown", (e) => {
        if (e.target.closest(".msg, #msg, .field input")) return;
        const selection = window.getSelection();
        if (selection && !selection.isCollapsed) selection.removeAllRanges();
    });
}
