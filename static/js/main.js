/* =========================================================
   main.js — 入口与装配
   只做两件事：按顺序初始化、把事件接到对应模块。
   业务细节分别在 state.js（状态）、api.js（请求）、ui.js（界面）、chat.js（聊天流程）。
   ========================================================= */

import { state, saveAuth } from "./state.js";
import * as api from "./api.js";
import * as ui from "./ui.js";
import * as chat from "./chat.js";

/** 把后端返回的 detail 写到登录表单下方；不是字符串时退回状态码。 */
function showAuthError(data, status) {
    ui.el.authMsg.textContent =
        typeof data.detail === "string" ? data.detail : ("请求失败 " + status);
}

/** 登录 / 注册表单：本地校验、提交、成功后进入聊天。 */
function initAuthForm() {
    ui.el.tabLogin.addEventListener("click", () => ui.setAuthMode("login"));
    ui.el.tabRegister.addEventListener("click", () => ui.setAuthMode("register"));

    // 密码框回车等同于点提交按钮，省一次移动鼠标
    [ui.el.passwordInput, ui.el.confirmInput].forEach((input) => {
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !ui.el.authSubmit.disabled) {
                e.preventDefault();
                ui.el.authSubmit.click();
            }
        });
    });

    ui.el.authSubmit.addEventListener("click", async () => {
        const username = ui.el.usernameInput.value.trim();
        const password = ui.el.passwordInput.value;
        ui.el.authMsg.textContent = "";

        if (!username || !password) {
            ui.el.authMsg.textContent = "请输入用户名和密码";
            return;
        }
        if (state.authMode === "register") {
            if (password.length < 6) {
                ui.el.authMsg.textContent = "密码至少 6 位";
                return;
            }
            if (password !== ui.el.confirmInput.value) {
                ui.el.authMsg.textContent = "两次输入的密码不一致";
                return;
            }
        }

        ui.el.authSubmit.disabled = true;
        try {
            if (state.authMode === "register") {
                const { ok, status, data } = await api.register(username, password);
                if (!ok) {
                    showAuthError(data, status);
                    return;
                }
                // 注册成功后不直接登录，让用户自己登一次，流程更清楚
                ui.clearAuthFields();
                ui.setAuthMode("login");
                ui.el.authMsg.textContent = "注册成功，请登录";
                return;
            }

            const { ok, status, data } = await api.login(username, password);
            if (!ok) {
                showAuthError(data, status);
                return;
            }

            saveAuth(data.access_token, username);
            ui.el.userName.textContent = username;
            ui.clearAuthFields();
            ui.hideAuth();
            await chat.loadInitialHistory();
        } catch (e) {
            ui.el.authMsg.textContent = "网络错误，请稍后重试";
        } finally {
            ui.el.authSubmit.disabled = false;
        }
    });
}

/** 右上角用户菜单：展开/收起、点外部关闭、设置与退出登录。 */
function initUserMenu() {
    ui.el.userMenuBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        ui.el.userMenu.hidden = !ui.el.userMenu.hidden;
    });

    document.addEventListener("click", (e) => {
        if (!ui.el.userMenu.hidden
            && !ui.el.userMenu.contains(e.target)
            && e.target !== ui.el.userMenuBtn) {
            ui.el.userMenu.hidden = true;
        }
    });

    // 「记忆大脑」跳到长期记忆的可视化页；登录态在 localStorage，跳转后仍然有效
    ui.el.menuBrain.addEventListener("click", () => {
        ui.el.userMenu.hidden = true;
        window.location.href = "/brain";
    });

    // 「设置」就是 API Key 弹窗，和输入栏里的按钮是同一个入口
    ui.el.menuConfig.addEventListener("click", () => {
        ui.el.userMenu.hidden = true;
        ui.el.apiKeyChip.click();
    });

    ui.el.menuLogout.addEventListener("click", () => {
        ui.el.userMenu.hidden = true;
        ui.showAuth();
    });
}

/** 输入区：自动增高、回车发送、点示例问题填进输入框。 */
function initComposer() {
    ui.el.msgInput.addEventListener("input", () => {
        ui.autoGrow();
        ui.updateSendState();
    });

    ui.el.msgInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey && !ui.el.sendBtn.disabled) {
            e.preventDefault();
            ui.el.sendBtn.click();
        }
    });

    ui.el.sendBtn.addEventListener("click", () => {
        const text = ui.el.msgInput.value.trim();
        if (text) chat.sendMessage(text);
    });

    document.querySelectorAll(".suggestion").forEach((btn) => {
        btn.addEventListener("click", () => {
            ui.el.msgInput.value = btn.dataset.prompt || btn.textContent;
            ui.autoGrow();
            ui.updateSendState();
            ui.el.msgInput.focus();
        });
    });
}

/** 消息区滚到顶部时自动加载更早的一页。 */
function initHistoryPaging() {
    ui.el.output.addEventListener("scroll", () => {
        if (ui.el.output.scrollTop <= 8) chat.loadOlderHistory();
    });
}

/**
 * 启动：先绑事件，再判断登录态。
 * 本地有 token 就直接进聊天并拉最新一页历史，否则停在登录页。
 */
async function boot() {
    ui.initUi();
    initAuthForm();
    initUserMenu();
    initComposer();
    initHistoryPaging();

    if (state.token) {
        if (state.username) ui.el.userName.textContent = state.username;
        ui.refreshApiKeyChip();
        ui.hideAuth();
        await chat.loadInitialHistory();
    } else {
        ui.setAuthMode("login");
        ui.showAuth();
    }
}

boot();
