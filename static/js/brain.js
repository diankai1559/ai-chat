/* =========================================================
   brain.js — 记忆大脑页（深空神经网络）
   数据来自 GET /memory/graph：常驻画像 + 每段记忆的摘要与标签。
   本文件做三件事：搭一片大脑点云做背景 → 把记忆按标签挂成发光网络 → 处理点击与详情。
   渲染用 three.js（本地 vendor，不走 CDN），交互交给 OrbitControls。
   ========================================================= */

import * as THREE from "three";
import { OrbitControls } from "three/addons/OrbitControls.js";
import { fetchMemoryGraph } from "./api.js";

/* ---------- 常量 ---------- */

// 标签节点的配色，取自参考页的学习区域色板
const PALETTE = ["#8f7cff", "#ff987d", "#59ded4", "#ffcc70", "#f782bd", "#74df92"];

// 四种分组方式：一个片段可以同时属于多个分组（人物标签是多值的）
const MODES = {
    topic: (seg) => [seg.tags.topic || "未归类"],
    people: (seg) => (seg.tags.people && seg.tags.people.length ? seg.tags.people : ["没提到别人"]),
    place: (seg) => [seg.tags.place || "没提到地点"],
    emotion: (seg) => [seg.tags.emotion || "平静"],
};

// 分组方式的中文名，用在导航与详情副标题
const MODE_LABELS = { topic: "话题", people: "人物", place: "地点", emotion: "情绪" };

// 相机基准距离：100% 缩放时相机到大脑中心的距离
const BASE_DISTANCE = 17;
// 点击标签/片段时自动推近的距离
const FOCUS_DISTANCE = 9.5;

/* ---------- 页面元素 ---------- */

const sceneEl = document.getElementById("scene");
const labelsEl = document.getElementById("labels");

const el = {
    scene: sceneEl,
    labels: labelsEl,
    headerSub: document.getElementById("headerSub"),
    stats: document.getElementById("stats"),
    nav: document.getElementById("nav"),
    zoomOut: document.getElementById("zoomOut"),
    zoomIn: document.getElementById("zoomIn"),
    zoomRange: document.getElementById("zoomRange"),
    zoomLabel: document.getElementById("zoomLabel"),
    detail: document.getElementById("detail"),
    detailTag: document.getElementById("detailTag"),
    detailTitle: document.getElementById("detailTitle"),
    detailSub: document.getElementById("detailSub"),
    detailBody: document.getElementById("detailBody"),
    detailClose: document.getElementById("detailClose"),
    empty: document.getElementById("empty"),
    emptyTitle: document.getElementById("emptyTitle"),
    emptyText: document.getElementById("emptyText"),
    emptyAction: document.getElementById("emptyAction"),
};

/* ---------- 运行状态 ---------- */

// 数据与图结构
const store = {
    profile: "",
    segments: [],
    stats: { segments: 0, days: 0, profile_chars: 0 },
    mode: "topic",
    groups: [],        // 当前分组下的标签节点列表
    nodes: [],         // 中枢 + 标签 + 片段
    links: [],         // [{ a: node, b: node }]
    selected: null,    // 当前选中的节点
};

// 相机与缩放
const view = {
    userDistance: BASE_DISTANCE,   // 用户自己拉到的距离，取消选中后回到这里
    targetDistance: BASE_DISTANCE, // 正在缓动的目标距离
    focusPoint: new THREE.Vector3(0, 0, 0),
    lastPercent: 100,
    sliderActive: false,           // 手指还在拖缩放条时不回写滑杆，避免抖动
};

// three.js 运行时对象
let renderer;
let scene;
let camera;
let controls;
let clock;
let rafId = 0;
let spinTimer = 0;

let brainGroup;       // 背景大脑点云
let graphGroup;       // 记忆网络（每次切换分组整体重建）
let linksMaterial;    // 连线材质，选中时统一压暗
let labelItems = [];  // 屏幕标签 { el, node }
let pickables = [];   // 可点击的命中精灵
let pulses = [];      // 沿着脑沟移动的光点

const glowTexture = createGlowTexture();

/* ---------- 工具函数 ---------- */

/** HTML 转义：摘要来自模型，拼进 innerHTML 前必须转义。 */
function esc(text) {
    return String(text ?? "").replace(/[&<>"']/g, (c) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
    }[c]));
}

/** 按字符数截断并加省略号，用于抽屉里的两行摘要。 */
function short(text, limit) {
    const value = String(text ?? "").replace(/\s+/g, " ").trim();
    return value.length > limit ? value.slice(0, limit) + "…" : value;
}

/** 限制在 [lo, hi] 区间。 */
function clamp(value, lo, hi) {
    return Math.max(lo, Math.min(hi, value));
}

/** 固定种子伪随机：同一个 key 每次刷新得到同一个位置。 */
function hash(value) {
    let h = 2166136261;
    for (const ch of String(value)) {
        h ^= ch.charCodeAt(0);
        h = Math.imul(h, 16777619);
    }
    return (h >>> 0) / 4294967295;
}

/** 生成一张径向发光贴图，所有光点共用（不重复创建）。 */
function createGlowTexture() {
    const size = 128;
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext("2d");
    const gradient = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    gradient.addColorStop(0, "rgba(255,255,255,1)");
    gradient.addColorStop(0.18, "rgba(220,235,255,.85)");
    gradient.addColorStop(0.44, "rgba(140,180,255,.28)");
    gradient.addColorStop(1, "rgba(60,110,255,0)");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, size, size);

    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
}

/* ---------- 大脑几何 ---------- */

/**
 * 半球点云：按斐波那契球面采样，再叠三层正弦褶皱，
 * 让表面看起来像脑回，而不是光滑的椭球。坐标从参考页移植。
 */
function hemisphereGeometry(side, count, seed = 0) {
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const base = new THREE.Color();
    const night = new THREE.Color("#0b1b3c");
    const tint = new THREE.Color(side < 0 ? "#7fb2ff" : "#9d8bff");
    const golden = Math.PI * (3 - Math.sqrt(5));

    for (let i = 0; i < count; i++) {
        const t = (i + 0.5) / count;
        const y0 = 1 - 2 * t;
        const rr = Math.sqrt(1 - y0 * y0);
        const a = i * golden + seed;
        const x0 = Math.abs(rr * Math.cos(a));
        const z0 = rr * Math.sin(a);

        const fold =
            0.072 * Math.sin(9 * Math.atan2(z0, x0) + 5 * y0) +
            0.045 * Math.sin(21 * z0 - 7 * y0) +
            0.026 * Math.sin(37 * y0 + 11 * z0);
        const b = 1 + fold;

        const frontal = Math.max(0, z0) * (0.34 + 0.18 * (1 - Math.abs(y0)));
        const temporal = y0 < -0.08
            ? 0.34 * (1 - Math.abs(y0)) * Math.max(0.1, 1 - Math.abs(z0))
            : 0;
        const occipital = z0 < 0 ? 0.16 * Math.max(0, 1 - Math.abs(y0)) : 0;

        const x = side * (0.26 + (4.54 + temporal) * x0 * b);
        const y = 3.25 * y0 * (1 + 0.025 * Math.sin(7 * a)) - 0.11 * Math.max(0, z0) * (1 - y0 * y0);
        const z = (3.76 + frontal + occipital) * z0 * b + 0.16 * Math.max(0, z0) * Math.sqrt(1 - y0 * y0);

        positions[i * 3] = x;
        positions[i * 3 + 1] = y;
        positions[i * 3 + 2] = z;

        base.set(tint).lerp(night, 0.55 + hash(`${seed}:${i}`) * 0.3);
        colors[i * 3] = base.r;
        colors[i * 3 + 1] = base.g;
        colors[i * 3 + 2] = base.b;
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    return geometry;
}

/**
 * 大脑表面单点：标签节点与表面信号都靠它定位，
 * 与 hemisphereGeometry 用同一套褶皱参数，位置才对得上。
 */
function brainSurfacePoint(side, theta, phi, lift = 0) {
    const y0 = Math.cos(theta);
    const r = Math.sin(theta);
    const x0 = Math.abs(r * Math.cos(phi));
    const z0 = r * Math.sin(phi);

    const fold =
        0.072 * Math.sin(9 * Math.atan2(z0, x0) + 5 * y0) +
        0.045 * Math.sin(21 * z0 - 7 * y0) +
        0.026 * Math.sin(37 * y0 + 11 * z0);
    const b = 1 + fold;

    const frontal = Math.max(0, z0) * (0.34 + 0.18 * (1 - Math.abs(y0)));
    const temporal = y0 < -0.08
        ? 0.34 * (1 - Math.abs(y0)) * Math.max(0.1, 1 - Math.abs(z0))
        : 0;
    const occipital = z0 < 0 ? 0.16 * Math.max(0, 1 - Math.abs(y0)) : 0;

    return new THREE.Vector3(
        side * (0.26 + (4.54 + temporal) * x0 * b + lift),
        3.25 * y0 * (1 + 0.025 * Math.sin(7 * phi)) - 0.11 * Math.max(0, z0) * (1 - y0 * y0),
        (3.76 + frontal + occipital) * z0 * b + 0.16 * Math.max(0, z0) * Math.sqrt(1 - y0 * y0),
    );
}

/** 小脑：两团点云，补全后脑的轮廓，让整颗大脑不至于只有两个半球。 */
function addCerebellum(parent) {
    const positions = [];
    for (const side of [-1, 1]) {
        for (let i = 0; i < 1200; i++) {
            const u = hash(`cb:${side}:${i}`) * Math.PI * 2;
            const v = hash(`cv:${side}:${i}`) * Math.PI;
            positions.push(
                side * (0.4 + Math.cos(u) * Math.sin(v) * 1.25),
                Math.cos(v) * 0.65 - 2.45,
                Math.sin(u) * Math.sin(v) * 0.82 - 2.55,
            );
        }
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));

    const points = new THREE.Points(geometry, new THREE.PointsMaterial({
        size: 0.055,
        map: glowTexture,
        color: "#6f9cff",
        transparent: true,
        opacity: 0.16,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
    }));
    parent.add(points);
}

/** 脑沟：几条很淡的曲线，负责「褶皱」的视觉暗示。 */
function addGyri(parent) {
    const material = new THREE.LineBasicMaterial({
        color: "#bed9ff",
        transparent: true,
        opacity: 0.055,
        blending: THREE.AdditiveBlending,
    });
    const sulci = [
        { theta: 0.84, phi: -1.15, span: 1.55 },
        { theta: 1.42, phi: -0.9, span: 1.65 },
        { theta: 1.96, phi: -0.74, span: 1.42 },
        { theta: 1.06, phi: 0.24, span: 1.35 },
        { theta: 1.68, phi: 0.36, span: 1.18 },
        { theta: 2.25, phi: 0.02, span: 1.02 },
    ];

    for (const side of [-1, 1]) {
        for (const [index, sulcus] of sulci.entries()) {
            const points = [];
            for (let j = 0; j < 48; j++) {
                const u = j / 47 - 0.5;
                points.push(brainSurfacePoint(
                    side,
                    sulcus.theta + 0.11 * Math.sin(u * Math.PI * 2 + index),
                    sulcus.phi + u * sulcus.span,
                    0.02,
                ));
            }
            parent.add(new THREE.Line(
                new THREE.BufferGeometry().setFromPoints(points),
                material,
            ));
        }
    }
}

/**
 * 表面信号：6 条沿脑沟游走的亮线，每条配两个移动光点。
 * 这是整页「会呼吸」的来源，也让静态点云看起来像在放电。
 */
function addSurfaceSignals(parent) {
    const paths = [
        { side: -1, theta: 0.83, phi: -1.04, span: 1.12, color: "#68e2e6" },
        { side: 1, theta: 0.86, phi: -0.82, span: 1.18, color: "#9d8bff" },
        { side: -1, theta: 1.38, phi: -0.58, span: 1.34, color: "#66baff" },
        { side: 1, theta: 1.52, phi: -0.42, span: 1.25, color: "#7ef0d0" },
        { side: -1, theta: 1.1, phi: 0.34, span: 0.98, color: "#f5a2d0" },
        { side: 1, theta: 1.18, phi: 0.26, span: 1.02, color: "#89b6ff" },
    ];

    paths.forEach((path, index) => {
        const points = [];
        for (let step = 0; step < 44; step++) {
            const u = step / 43 - 0.5;
            points.push(brainSurfacePoint(
                path.side,
                path.theta + 0.09 * Math.sin(u * Math.PI * 2 + index),
                path.phi + u * path.span,
                0.09,
            ));
        }

        const curve = new THREE.CatmullRomCurve3(points);
        curve.arcLengthDivisions = 96;

        parent.add(new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(curve.getPoints(80)),
            new THREE.LineBasicMaterial({
                color: path.color,
                transparent: true,
                opacity: 0.19,
                depthWrite: false,
                blending: THREE.AdditiveBlending,
            }),
        ));

        // 每条信号两个光点，错开相位，看起来像信号在往前跑
        for (let k = 0; k < 2; k++) {
            const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
                map: glowTexture,
                color: k === 0 ? "#effcff" : path.color,
                transparent: true,
                opacity: k === 0 ? 0.9 : 0.4,
                depthWrite: false,
                blending: THREE.AdditiveBlending,
            }));
            sprite.scale.setScalar(k === 0 ? 0.075 : 0.05);
            parent.add(sprite);
            pulses.push({
                sprite,
                curve,
                offset: hash(`surface:${index}:${k}`),
                speed: 0.018 + hash(`surface-speed:${index}`) * 0.016,
            });
        }
    });
}

/** 组装背景大脑：两半球点云 + 内层衬底 + 小脑 + 脑干 + 脑沟 + 表面信号。 */
function buildBrain() {
    brainGroup = new THREE.Group();

    for (const [side, seed] of [[-1, 0], [1, 0.31]]) {
        const geometry = hemisphereGeometry(side, 5600, seed);

        brainGroup.add(new THREE.Points(geometry, new THREE.PointsMaterial({
            size: 0.031,
            vertexColors: true,
            transparent: true,
            opacity: 0.77,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
        })));

        // 内层衬底：稍微缩小、几乎透明，让边缘看起来有厚度
        const inner = new THREE.Points(geometry.clone(), new THREE.PointsMaterial({
            size: 0.012,
            color: "#c0dbff",
            transparent: true,
            opacity: 0.1,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
        }));
        inner.scale.setScalar(0.955);
        brainGroup.add(inner);
    }

    addCerebellum(brainGroup);
    addGyri(brainGroup);
    addSurfaceSignals(brainGroup);
    scene.add(brainGroup);
}

/* ---------- 记忆网络 ---------- */

/**
 * 把标签节点摆进大脑内部：取表面点再向中心收缩，
 * 收缩系数有随机差异，节点才有前后层次，不会都贴在同一个壳上。
 */
function placeGroupNode(i, thetaSeed) {
    const side = i % 2 === 0 ? -1 : 1;
    const theta = 0.5 + ((thetaSeed * 1.37) % 1) * 2.0;     // 0.5 ~ 2.5，避开正上下极
    const phi = (i * 2.399 + thetaSeed * 0.9) % (Math.PI * 2);
    const shrink = 0.5 + hash(`shrink:${i}`) * 0.16;         // 0.50 ~ 0.66
    return brainSurfacePoint(side, theta, phi).multiplyScalar(shrink);
}

/** 片段节点在所属标签附近散开，半径很小，保持「一团」的簇状结构。 */
function placeSegmentNode(center, i, j) {
    const u = hash(`su:${i}:${j}`) * Math.PI * 2;
    const v = hash(`sv:${i}:${j}`) * Math.PI;
    const radius = 0.2 + hash(`sr:${i}:${j}`) * 0.2;
    return new THREE.Vector3(
        center.x + Math.cos(u) * Math.sin(v) * radius,
        center.y + Math.cos(v) * radius,
        center.z + Math.sin(u) * Math.sin(v) * radius,
    );
}

/** 创建一颗发光精灵：可见点 + 独立命中区，点击时不用点中那几个像素。 */
function createNodeSprite(node, size, color, opacity, hitSize) {
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
        map: glowTexture,
        color,
        transparent: true,
        opacity,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
    }));
    sprite.position.copy(node.pos);
    sprite.scale.setScalar(size);
    sprite.userData.node = node;
    node.sprite = sprite;
    node.baseScale = size;
    node.baseOpacity = opacity;

    const hit = new THREE.Sprite(new THREE.SpriteMaterial({
        transparent: true,
        opacity: 0,
        colorWrite: false,
        depthWrite: false,
    }));
    hit.position.copy(node.pos);
    hit.scale.setScalar(hitSize);
    hit.userData.node = node;
    node.hit = hit;

    graphGroup.add(sprite, hit);
    pickables.push(hit);
    return sprite;
}

/** 清空旧的记忆网络：几何、材质都释放，避免切换分组时显存越积越多。 */
function disposeGraph() {
    if (graphGroup) {
        scene.remove(graphGroup);
        graphGroup.traverse((obj) => {
            if (obj.geometry) obj.geometry.dispose();
            if (obj.material) obj.material.dispose();
        });
        graphGroup = null;
    }
    linksMaterial = null;
    pickables = [];
    labelItems = [];
    labelsEl.innerHTML = "";
    store.nodes = [];
    store.links = [];
    store.groups = [];
}

/** 按当前分组方式重建记忆网络：中枢 → 标签节点 → 片段节点，外加连线与标签。 */
function buildGraph() {
    disposeGraph();

    const pick = MODES[store.mode];
    const groupsMap = new Map();
    for (const seg of store.segments) {
        for (const raw of pick(seg)) {
            const name = String(raw || "").trim() || "未归类";
            if (!groupsMap.has(name)) groupsMap.set(name, { name, segs: [] });
            const group = groupsMap.get(name);
            if (!group.segs.includes(seg)) group.segs.push(seg);
        }
    }
    const groups = [...groupsMap.values()].sort((a, b) => b.segs.length - a.segs.length);

    graphGroup = new THREE.Group();
    scene.add(graphGroup);

    // 1) 中枢：位于大脑中心的一颗金色亮核
    const core = {
        id: "core",
        type: "core",
        label: "小满的记忆",
        count: store.segments.length,
        color: "#ffe39a",
        pos: new THREE.Vector3(0, 0, 0),
        phase: 0,
    };
    createNodeSprite(core, 0.34, core.color, 1, 0.85);
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({
        map: glowTexture,
        color: core.color,
        transparent: true,
        opacity: 0.42,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
    }));
    halo.scale.setScalar(1.15);
    graphGroup.add(halo);
    core.halo = halo;
    store.nodes.push(core);

    // 2) 标签节点：颜色取自色板，大小随片段数增长
    const linkPositions = [];
    const linkColors = [];

    groups.forEach((group, i) => {
        const color = PALETTE[i % PALETTE.length];
        const node = {
            id: `g:${i}`,
            type: "group",
            label: group.name,
            count: group.segs.length,
            segs: group.segs,
            color,
            pos: placeGroupNode(i, hash(`group:${group.name}`)),
            phase: hash(`gphase:${group.name}`) * 6.28,
        };
        const size = 0.28 + Math.min(0.32, group.segs.length * 0.045);
        createNodeSprite(node, size, color, 0.95, size * 1.4 + 0.16);
        store.nodes.push(node);
        store.groups.push(node);
        store.links.push({ a: core, b: node });

        // 中枢 → 标签 的连线
        linkPositions.push(core.pos.x, core.pos.y, core.pos.z, node.pos.x, node.pos.y, node.pos.z);
        const c = new THREE.Color(color).lerp(new THREE.Color("#ffffff"), 0.35);
        linkColors.push(c.r, c.g, c.b, c.r, c.g, c.b);

        // 3) 片段节点：有待办的金色高亮，其余用标签色
        group.segs.forEach((seg, j) => {
            const hasLoop = (seg.tags.open_loops || []).length > 0;
            const segNode = {
                id: `s:${i}:${seg.seq}`,
                type: "seg",
                label: seg.day || "一段记忆",
                seq: seg.seq,
                parentId: node.id,
                seg,
                color: hasLoop ? "#ffe39a" : color,
                pos: placeSegmentNode(node.pos, i, j),
                phase: hash(`sphase:${i}:${j}`) * 6.28,
            };
            const segSize = 0.06 + (seg.tags.importance ?? 0.5) * 0.065;
            createNodeSprite(segNode, segSize, segNode.color, 0.85, 0.19);
            store.nodes.push(segNode);

            linkPositions.push(
                node.pos.x, node.pos.y, node.pos.z,
                segNode.pos.x, segNode.pos.y, segNode.pos.z,
            );
            const sc = new THREE.Color(color).multiplyScalar(0.7);
            linkColors.push(sc.r, sc.g, sc.b, sc.r, sc.g, sc.b);

            store.links.push({ a: node, b: segNode });
        });
    });

    // 4) 连线：一次画完所有线段，选中时只调一个材质透明度
    const linkGeometry = new THREE.BufferGeometry();
    linkGeometry.setAttribute("position", new THREE.Float32BufferAttribute(linkPositions, 3));
    linkGeometry.setAttribute("color", new THREE.Float32BufferAttribute(linkColors, 3));
    linksMaterial = new THREE.LineBasicMaterial({
        vertexColors: true,
        transparent: true,
        opacity: 0.26,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
    });
    graphGroup.add(new THREE.LineSegments(linkGeometry, linksMaterial));

    // 5) 屏幕标签：分组太多时只保留前 20 个，避免糊成一片
    buildLabels(store.groups.slice(0, 20));

    // 重建后选中状态一定是空的
    store.selected = null;
    el.detail.classList.remove("open");
    el.detail.setAttribute("aria-hidden", "true");
    view.focusPoint.set(0, 0, 0);
    view.targetDistance = view.userDistance;

    updateStats();
}

/** 给标签节点生成屏幕标签 DOM；位置在每帧里跟着投影更新。 */
function buildLabels(groupNodes) {
    labelsEl.innerHTML = "";
    labelItems = groupNodes.map((node) => {
        const label = document.createElement("div");
        label.className = "node-label";
        label.textContent = `${node.label} · ${node.count}`;
        labelsEl.appendChild(label);
        return { el: label, node, w: 90, h: 20 };
    });

    // 量一次尺寸，后面的碰撞检测就不用每帧触发重排
    for (const item of labelItems) {
        item.w = item.el.offsetWidth || 90;
        item.h = item.el.offsetHeight || 20;
    }
}

/* ---------- 选中与高亮 ---------- */

/** 算出选中节点需要保持亮起的集合；返回 null 表示全部正常显示。 */
function highlightSet() {
    const node = store.selected;
    if (!node || node.type === "core") return null;

    const set = new Set(["core", node.id]);
    if (node.type === "group") {
        for (const item of store.nodes) {
            if (item.parentId === node.id) set.add(item.id);
        }
    } else if (node.parentId) {
        set.add(node.parentId);
    }
    return set;
}

/** 把高亮落到材质上：亮集合外的节点压暗，连线整体压暗。 */
function applyHighlight() {
    const set = highlightSet();
    for (const node of store.nodes) {
        const lit = !set || set.has(node.id);
        node.sprite.material.opacity = node.baseOpacity * (lit ? 1 : 0.18);
        if (node.halo) node.halo.material.opacity = (lit ? 0.42 : 0.1);
    }
    if (linksMaterial) linksMaterial.opacity = set ? 0.09 : 0.26;
}

/** 选中节点：推近相机、打开右侧详情、压暗其他节点。 */
function select(node) {
    store.selected = node;
    view.focusPoint.copy(node.pos);
    view.targetDistance = node.type === "core" ? view.userDistance : FOCUS_DISTANCE;

    applyHighlight();
    renderDetail(node);
    el.detail.classList.add("open");
    el.detail.setAttribute("aria-hidden", "false");
    el.detail.scrollTop = 0;
}

/** 取消选中：相机回到全脑视角，详情收起，全部节点恢复亮度。 */
function clearSelection() {
    store.selected = null;
    view.focusPoint.set(0, 0, 0);
    view.targetDistance = view.userDistance;
    applyHighlight();
    el.detail.classList.remove("open");
    el.detail.setAttribute("aria-hidden", "true");
}

/* ---------- 详情抽屉 ---------- */

/** 一段记忆的条目按钮；data-seq 用来点进去看完整内容。 */
function memItem(seg, color) {
    const loop = (seg.tags.open_loops || []).length > 0;
    return `
        <button class="mem-item${loop ? " lit" : ""}" type="button" data-seq="${seg.seq}">
            <i style="color:${loop ? "#ffe39a" : color}"></i>
            <span>
                <strong>${esc(seg.day || "一段记忆")}</strong>
                <small>${esc(short(seg.summary, 70))}</small>
            </span>
            <b>${seg.turns} 条</b>
        </button>`;
}

/** 标签胶囊：时间/地点/情绪/话题/人物/待办。 */
function renderTags(tags) {
    const items = [];
    if (tags.time) items.push(`时间 · ${tags.time}`);
    if (tags.place) items.push(`地点 · ${tags.place}`);
    if (tags.emotion) items.push(`情绪 · ${tags.emotion}`);
    if (tags.topic) items.push(`话题 · ${tags.topic}`);
    for (const person of tags.people || []) items.push(`人物 · ${person}`);
    for (const loop of tags.open_loops || []) items.push(`待办 · ${loop}`);
    if (!items.length) return "";
    return `<div class="tag-row">${items.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>`;
}

/** 根据节点类型写抽屉：中枢看画像，标签看列表，片段看完整摘要。 */
function renderDetail(node) {
    if (node.type === "core") {
        el.detailTag.textContent = "PROFILE";
        el.detailTag.style.color = "#ffe6a5";
        el.detailTitle.textContent = "常驻画像";
        el.detailSub.textContent = `长期保留的稳定信息 · ${store.stats.profile_chars} 字`;
        el.detailBody.innerHTML = `
            <div class="profile-full">${esc(store.profile || "还没有形成常驻画像，多聊几次就会有了。")}</div>
            <p class="detail-heading">她现在记得</p>
            <div class="tag-row">
                <span class="tag">${store.stats.segments} 段记忆</span>
                <span class="tag">${store.stats.days} 天</span>
                <span class="tag">${countOpenLoops()} 件待办</span>
            </div>`;
        return;
    }

    if (node.type === "group") {
        const segs = [...node.segs].sort((a, b) => b.ts - a.ts);
        el.detailTag.textContent = "TAG CLUSTER";
        el.detailTag.style.color = node.color;
        el.detailTitle.textContent = node.label;
        el.detailSub.textContent = `这里有 ${node.count} 段记忆 · 按${MODE_LABELS[store.mode]}`;
        el.detailBody.innerHTML = segs.map((seg) => memItem(seg, node.color)).join("");
        return;
    }

    const seg = node.seg;
    const parent = store.nodes.find((item) => item.id === node.parentId);
    const tagHtml = renderTags(seg.tags);
    el.detailTag.textContent = "MEMORY SEGMENT";
    el.detailTag.style.color = node.color;
    el.detailTitle.textContent = seg.day || "一段记忆";
    el.detailSub.textContent = `${seg.turns} 条消息 · ${seg.tags.topic || "未归类"}`;
    el.detailBody.innerHTML = `
        ${parent ? `<button class="back-to-group" type="button" data-back="${parent.id}">← 回到「${esc(parent.label)}」</button>` : ""}
        <div class="mem-full">${esc(seg.summary)}</div>
        ${tagHtml ? `<p class="detail-heading">标签</p>${tagHtml}` : ""}`;
}

/* ---------- 统计与导航 ---------- */

/** 统计待办数量：有 open_loops 的片段算一件。 */
function countOpenLoops() {
    return store.segments.filter((seg) => (seg.tags.open_loops || []).length > 0).length;
}

/** 某一种分组方式下有多少个标签，用在左侧导航的数字上。 */
function groupCountFor(mode) {
    const names = new Set();
    const pick = MODES[mode];
    for (const seg of store.segments) {
        for (const raw of pick(seg)) {
            names.add(String(raw || "").trim() || "未归类");
        }
    }
    return names.size;
}

/** 顶部统计卡：片段 / 标签 / 连接 / 待办（待办用金色）。 */
function updateStats() {
    const loops = countOpenLoops();
    const cells = [
        { value: store.segments.length, label: "记忆片段" },
        { value: store.groups.length, label: "标签" },
        { value: store.links.length, label: "连接" },
    ];
    if (loops) cells.push({ value: loops, label: "待办", gold: true });

    el.stats.innerHTML = cells.map((cell) => `
        <span class="${cell.gold ? "frontier-stat" : ""}">
            <b>${cell.value}</b>${cell.label}
        </span>`).join("");
}

/** 左侧（手机端底部）的分组导航：四种检索视角 + 各自标签数。 */
function buildNav() {
    const modes = Object.keys(MODES);
    el.nav.innerHTML = modes.map((mode, i) => `
        <button type="button" data-mode="${mode}" class="${mode === store.mode ? "active" : ""}">
            <i style="color:${PALETTE[i % PALETTE.length]}"></i>
            ${MODE_LABELS[mode]}
            <b>${groupCountFor(mode)}</b>
        </button>`).join("");
}

/** 空状态 / 未登录提示。 */
function showEmpty(title, text, href, action) {
    el.emptyTitle.textContent = title;
    el.emptyText.textContent = text;
    el.emptyAction.textContent = action;
    el.emptyAction.href = href;
    el.empty.hidden = false;
}

/* ---------- 场景与相机 ---------- */

/** 容器尺寸变化时同步渲染器与相机；竖屏用更宽的视角把整颗大脑装进来。 */
function resize() {
    if (!renderer || !camera) return;

    const width = sceneEl.clientWidth || 1;
    const height = sceneEl.clientHeight || 1;

    renderer.setSize(width, height, false);

    camera.aspect = width / height;
    const horizontalFov = 2 * Math.atan(12.2 / 2 / BASE_DISTANCE);   // 横向装下整颗大脑，留一点边距
    const verticalFov = THREE.MathUtils.radToDeg(
        2 * Math.atan(Math.tan(horizontalFov / 2) / camera.aspect),
    );
    camera.fov = clamp(verticalFov, 30, 88);
    camera.updateProjectionMatrix();

    viewProjectionSize = { width, height };
}

/** 投影用到的画布尺寸，跟着 resize 更新。 */
let viewProjectionSize = { width: 1, height: 1 };

/** 初始化 three.js：场景、相机、控制器、渲染器与背景大脑。 */
function initScene() {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    sceneEl.appendChild(renderer.domElement);

    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(38, 1, 0.1, 200);
    // 斜一点的机位：正对时两个半球会叠成一个椭圆，侧一些才看得出脑形
    camera.position.set(4.2, 2.3, BASE_DISTANCE - 1.6);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.enablePan = false;
    controls.enableZoom = false;         // 缩放由下方的滚轮/双指逻辑接管
    controls.rotateSpeed = 0.55;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.6;
    controls.minPolarAngle = 0.18;
    controls.maxPolarAngle = Math.PI - 0.18;

    // 用户一碰就停转，松手 2.5 秒后再慢慢转起来
    controls.addEventListener("start", () => {
        controls.autoRotate = false;
        clearTimeout(spinTimer);
    });
    controls.addEventListener("end", () => {
        clearTimeout(spinTimer);
        spinTimer = setTimeout(() => { controls.autoRotate = true; }, 2500);
    });

    clock = new THREE.Clock();

    buildBrain();
    resize();
}

/* ---------- 动画循环 ---------- */

/** 相机距离缓动：点选时推近，取消时回到用户自己拉到的尺度。 */
function easeCamera(dt) {
    const distance = camera.position.distanceTo(controls.target);
    if (Math.abs(distance - view.targetDistance) > 0.02) {
        const direction = camera.position.clone().sub(controls.target).normalize();
        const next = distance + (view.targetDistance - distance) * Math.min(1, dt * 5);
        camera.position.copy(controls.target).addScaledVector(direction, next);
    }
    controls.target.lerp(view.focusPoint, Math.min(1, dt * 4));
}

/** 表面信号沿线推进；每条信号两个光点错开半圈。 */
function updatePulses(dt) {
    for (const pulse of pulses) {
        pulse.offset = (pulse.offset + pulse.speed * dt) % 1;
        pulse.sprite.position.copy(pulse.curve.getPointAt(pulse.offset));
    }
}

/** 节点呼吸：大小轻微起伏，选中的那颗再放大一点。 */
function updateBreath(now) {
    for (const node of store.nodes) {
        const amplitude = node.type === "seg" ? 0.004 : 0.018;
        const boost = node === store.selected ? 1.2 : 1;
        const scale = node.baseScale * boost + Math.sin(now * 0.0012 + node.phase) * amplitude;
        node.sprite.scale.setScalar(scale);
    }
}

/** 把标签节点投影到屏幕：超出视野或与已放标签相撞就隐藏，越远越淡。 */
function updateLabels() {
    if (!labelItems.length) return;

    const { width, height } = viewProjectionSize;
    const projected = new THREE.Vector3();
    const placed = [];

    for (const item of labelItems) {
        projected.copy(item.node.pos);
        projected.y += 0.28;
        projected.project(camera);

        if (projected.z > 1) {
            item.el.style.opacity = "0";
            continue;
        }

        const x = (projected.x * 0.5 + 0.5) * width;
        const y = (-projected.y * 0.5 + 0.5) * height;

        if (x < -40 || x > width + 40 || y < -20 || y > height + 20) {
            item.el.style.opacity = "0";
            continue;
        }

        // 矩形相交就藏起来：宁可少显示两个，也不要糊成一团
        const rect = {
            x1: x - item.w / 2 - 3,
            x2: x + item.w / 2 + 3,
            y1: y - item.h / 2 - 2,
            y2: y + item.h / 2 + 2,
        };
        const clash = placed.some((other) => !(
            rect.x2 < other.x1 || rect.x1 > other.x2 || rect.y2 < other.y1 || rect.y1 > other.y2
        ));
        if (clash) {
            item.el.style.opacity = "0";
            continue;
        }
        placed.push(rect);

        const distance = camera.position.distanceTo(item.node.pos);
        const opacity = clamp(1.05 - (distance - 8) / 26, 0.5, 1);

        item.el.style.opacity = String(opacity);
        item.el.style.transform = `translate(-50%, -50%) translate(${x}px, ${y}px)`;
    }
}

/** 缩放百分比显示：100% 对应基准距离，拉近则百分比变大。 */
function syncZoomUI() {
    const distance = camera.position.distanceTo(controls.target);
    const percent = clamp(Math.round((BASE_DISTANCE / distance) * 100), 40, 260);
    if (percent === view.lastPercent) return;

    view.lastPercent = percent;
    el.zoomLabel.textContent = `${percent}%`;
    if (!view.sliderActive) el.zoomRange.value = String(percent);
}

/** 每帧：推进相机与动效，再把场景画出来。 */
function animate() {
    rafId = requestAnimationFrame(animate);

    const dt = Math.min(0.05, clock.getDelta());
    const now = performance.now();

    easeCamera(dt);
    controls.update();

    updatePulses(dt);
    updateBreath(now);
    updateLabels();
    syncZoomUI();

    renderer.render(scene, camera);
}

/* ---------- 交互 ---------- */

/** 视口坐标 → 射线，返回最近的命中节点；没有命中返回 null。 */
function pickNode(clientX, clientY) {
    const rect = renderer.domElement.getBoundingClientRect();
    const pointer = new THREE.Vector2(
        ((clientX - rect.left) / rect.width) * 2 - 1,
        -((clientY - rect.top) / rect.height) * 2 + 1,
    );
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(pointer, camera);

    const hits = raycaster.intersectObjects(pickables, false);
    return hits.length ? hits[0].object.userData.node : null;
}

/**
 * 指针交互：按下记录起点，抬起时位移小于 8px 才算点击。
 * 双指时临时关掉 OrbitControls，自己算捏合缩放，避免两套逻辑互相抢。
 */
function bindInteractions() {
    const dom = renderer.domElement;
    const pointers = new Map();
    let down = null;
    let pinchStart = 0;
    let pinchDistance = 0;
    let lastHoverAt = 0;

    dom.addEventListener("pointerdown", (e) => {
        pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
        down = { x: e.clientX, y: e.clientY, moved: 0, at: performance.now() };

        if (pointers.size === 2) {
            down = null;                    // 双指不再算点击
            controls.enabled = false;
            const [a, b] = [...pointers.values()];
            pinchStart = Math.hypot(a.x - b.x, a.y - b.y);
            pinchDistance = view.targetDistance;
        }
    });

    dom.addEventListener("pointermove", (e) => {
        if (pointers.has(e.pointerId)) {
            pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
        }

        // 双指捏合：两指距离变大 → 拉近
        if (pointers.size >= 2 && pinchStart > 0) {
            const [a, b] = [...pointers.values()];
            const distance = Math.hypot(a.x - b.x, a.y - b.y);
            view.targetDistance = clamp(pinchDistance * (pinchStart / Math.max(1, distance)), 6, 40);
            view.userDistance = view.targetDistance;
            return;
        }

        if (down) {
            down.moved = Math.max(down.moved, Math.hypot(e.clientX - down.x, e.clientY - down.y));
            return;
        }

        // 悬停：轻微节流，避免每帧都做射线检测
        const now = performance.now();
        if (now - lastHoverAt < 70) return;
        lastHoverAt = now;
        dom.style.cursor = pickNode(e.clientX, e.clientY) ? "pointer" : "grab";
    });

    dom.addEventListener("pointerup", (e) => {
        pointers.delete(e.pointerId);

        if (pointers.size < 2) {
            controls.enabled = true;
            pinchStart = 0;
        }

        if (pointers.size === 0) {
            if (down && down.moved < 8 && performance.now() - down.at < 500) {
                const node = pickNode(e.clientX, e.clientY);
                if (node) select(node);
                else clearSelection();
            }
            down = null;
        }
    });

    dom.addEventListener("pointercancel", (e) => {
        pointers.delete(e.pointerId);
        down = null;
        pinchStart = 0;
        controls.enabled = true;
    });

    // 滚轮缩放：自己接管，OrbitControls 的 zoom 已关掉
    dom.addEventListener("wheel", (e) => {
        e.preventDefault();
        const factor = e.deltaY > 0 ? 1.12 : 0.89;
        view.targetDistance = clamp(view.targetDistance * factor, 6, 40);
        view.userDistance = view.targetDistance;
    }, { passive: false });

    // 左侧 / 底部导航：切换分组方式后整张网重建，详情自动收起
    el.nav.addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-mode]");
        if (!btn || btn.dataset.mode === store.mode) return;

        store.mode = btn.dataset.mode;
        el.nav.querySelectorAll("button").forEach((item) => {
            item.classList.toggle("active", item === btn);
        });
        buildGraph();
    });

    // 详情抽屉右上角的关闭按钮
    el.detailClose.addEventListener("click", clearSelection);

    // 抽屉里点记忆条目 → 选中对应片段；点「回到标签」→ 回到分组
    el.detailBody.addEventListener("click", (e) => {
        const back = e.target.closest("[data-back]");
        if (back) {
            const node = store.nodes.find((item) => item.id === back.dataset.back);
            if (node) select(node);
            return;
        }

        const item = e.target.closest("[data-seq]");
        if (!item) return;

        const seq = Number(item.dataset.seq);
        const node = store.nodes.find((n) => n.type === "seg" && n.seq === seq);
        if (node) select(node);
    });

    el.zoomRange.addEventListener("input", (e) => {
        const percent = Number(e.target.value);
        view.targetDistance = clamp((BASE_DISTANCE * 100) / percent, 6, 40);
        view.userDistance = view.targetDistance;
    });
    // 拖动滑杆期间暂停百分比回写，松手后再同步一次
    el.zoomRange.addEventListener("pointerdown", () => { view.sliderActive = true; });
    el.zoomRange.addEventListener("pointerup", () => { view.sliderActive = false; });
    el.zoomRange.addEventListener("pointercancel", () => { view.sliderActive = false; });

    el.zoomIn.addEventListener("click", () => {
        view.targetDistance = clamp(view.targetDistance * 0.82, 6, 40);
        view.userDistance = view.targetDistance;
    });
    el.zoomOut.addEventListener("click", () => {
        view.targetDistance = clamp(view.targetDistance * 1.22, 6, 40);
        view.userDistance = view.targetDistance;
    });
    el.zoomLabel.addEventListener("click", () => {
        view.userDistance = BASE_DISTANCE;
        view.targetDistance = BASE_DISTANCE;
        view.focusPoint.set(0, 0, 0);
        store.selected = null;
        applyHighlight();
        el.detail.classList.remove("open");
        el.detail.setAttribute("aria-hidden", "true");
    });

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") clearSelection();
    });

    window.addEventListener("resize", resize);
    window.addEventListener("orientationchange", resize);
}

/* ---------- 启动 ---------- */

/** 拉数据 → 建导航/网络/统计；401 与其它失败分别给不同文案。 */
async function load() {
    try {
        const data = await fetchMemoryGraph();

        store.profile = data.profile || "";
        store.segments = (data.segments || []).map((item) => ({
            seq: item.seq,
            summary: item.summary || "",
            tags: item.tags || {},
            turns: item.turns || 0,
            day: item.day || "",
            ts: item.ts || 0,
        }));
        store.stats = data.stats || {
            segments: store.segments.length,
            days: new Set(store.segments.map((s) => s.day).filter(Boolean)).size,
            profile_chars: store.profile.length,
        };

        buildNav();
        buildGraph();

        el.headerSub.textContent = store.segments.length
            ? `她已经记住了 ${store.stats.segments} 段对话，分布在 ${store.stats.days} 天里。`
            : "还没有形成长期记忆，多聊几次就会亮起来。";

        if (!store.segments.length) {
            showEmpty(
                "还没有形成长期记忆",
                "和她多聊几次，一段对话结束后这里就会亮起一颗光点。",
                "/",
                "去聊会儿",
            );
        }
    } catch (error) {
        if (error && error.code === 401) {
            showEmpty("先登录，再来看她的记忆", "登录后这里会显示她记住的每件事。", "/", "去登录");
        } else {
            showEmpty("记忆读取失败", "可能是服务临时出了点问题，稍后再试试。", "/", "回到对话");
            el.headerSub.textContent = "读取失败";
        }
    }
}

/** 入口：建场景 → 绑交互 → 拉数据 → 开动画；WebGL 不可用时给一段文字提示。 */
function boot() {
    try {
        initScene();
    } catch (error) {
        console.error(error);
        showEmpty("这台设备暂时无法开启 3D 视图", "换一个支持 WebGL 的浏览器，或用手机再试试。", "/", "回到对话");
        return;
    }

    bindInteractions();
    load();
    rafId = requestAnimationFrame(animate);
}

boot();
