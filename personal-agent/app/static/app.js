const skillsList = document.getElementById("skills-list");
const viewerTitle = document.getElementById("viewer-title");
const viewerBody = document.getElementById("viewer-body");
const btnDeleteSkill = document.getElementById("btn-delete-skill");
const chatLog = document.getElementById("chat-log");
const execLog = document.getElementById("exec-log");
const chatInput = document.getElementById("chat-input");
const modalRoot = document.getElementById("modal-root");

let activeSkill = null;

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText);
  }
  return res.json();
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) node.appendChild(c);
  return node;
}

// ---------- skills list ----------

async function loadSkills() {
  const skills = await api("/api/skills");
  skillsList.innerHTML = "";
  for (const s of skills) {
    const item = el("div", {
      class: "skill-item" + (activeSkill === s.name ? " active" : ""),
      onclick: () => selectSkill(s.name),
    }, [
      el("div", { class: "name", text: s.name }),
      el("div", { class: "desc", text: s.description || "(no description)" }),
    ]);
    skillsList.appendChild(item);
  }
  if (skills.length === 0) {
    skillsList.appendChild(el("div", { class: "hint", text: "还没有安装任何 skill。" }));
  }
}

async function selectSkill(name) {
  activeSkill = name;
  await loadSkills();
  const s = await api(`/api/skills/${encodeURIComponent(name)}`);
  viewerTitle.textContent = s.name;
  btnDeleteSkill.style.display = "inline-block";
  viewerBody.innerHTML = "";

  const tree = el("ul", { class: "file-tree" });
  for (const f of s.files) {
    tree.appendChild(el("li", { text: f, onclick: () => showFile(name, f) }));
  }
  viewerBody.appendChild(el("div", { text: "Files:" }));
  viewerBody.appendChild(tree);
  viewerBody.appendChild(el("div", { text: "SKILL.md instructions:", style: "margin-top:10px" }));
  viewerBody.appendChild(el("pre", { class: "instructions", text: s.instructions }));
}

async function showFile(name, path) {
  const { content } = await api(`/api/skills/${encodeURIComponent(name)}/file?path=${encodeURIComponent(path)}`);
  const existing = document.getElementById("file-content");
  if (existing) existing.remove();
  const pre = el("pre", { id: "file-content", text: `--- ${path} ---\n${content}` });
  viewerBody.appendChild(pre);
  pre.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

btnDeleteSkill.addEventListener("click", async () => {
  if (!activeSkill) return;
  if (!confirm(`Delete skill "${activeSkill}"?`)) return;
  await api(`/api/skills/${encodeURIComponent(activeSkill)}`, { method: "DELETE" });
  activeSkill = null;
  viewerTitle.textContent = "Select a skill";
  viewerBody.innerHTML = "";
  btnDeleteSkill.style.display = "none";
  loadSkills();
});

// ---------- modals ----------

function openModal(title, fields, onSubmit) {
  modalRoot.innerHTML = "";
  const inputs = {};
  const fieldNodes = fields.map((f) => {
    const input = f.multiline
      ? el("textarea", { id: `f-${f.name}`, placeholder: f.placeholder || "" })
      : el("input", { id: `f-${f.name}`, type: "text", placeholder: f.placeholder || "" });
    inputs[f.name] = input;
    return el("div", {}, [el("label", { text: f.label }), input]);
  });

  const errorBox = el("div", { class: "hint", style: "color:var(--err);display:none" });

  const modal = el("div", { class: "modal" }, [
    el("h3", { text: title }),
    ...fieldNodes,
    errorBox,
    el("div", { class: "actions" }, [
      el("button", { class: "btn small", text: "Cancel", onclick: () => (modalRoot.innerHTML = "") }),
      el("button", {
        class: "btn",
        text: "Submit",
        onclick: async () => {
          const values = {};
          for (const [k, node] of Object.entries(inputs)) values[k] = node.value.trim();
          try {
            await onSubmit(values);
            modalRoot.innerHTML = "";
          } catch (e) {
            errorBox.textContent = e.message;
            errorBox.style.display = "block";
          }
        },
      }),
    ]),
  ]);
  modalRoot.appendChild(el("div", { class: "modal-backdrop" }, [modal]));
}

document.getElementById("btn-new-skill").addEventListener("click", () => {
  openModal("Create skill", [
    { name: "name", label: "Name (slug)", placeholder: "e.g. pdf-merge" },
    { name: "description", label: "Description", placeholder: "when should this skill be used?" },
    { name: "content", label: "Instructions (markdown)", multiline: true },
  ], async (v) => {
    await api("/api/skills", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(v),
    });
    await loadSkills();
  });
});

document.getElementById("btn-download-skill").addEventListener("click", () => {
  openModal("Download skill from git", [
    { name: "repo_url", label: "Repo URL (https://...)", placeholder: "https://github.com/anthropics/skills" },
    { name: "skill_path", label: "Skill subdirectory (optional)", placeholder: "e.g. pdf" },
    { name: "rename", label: "Local name (optional)" },
  ], async (v) => {
    const body = { repo_url: v.repo_url };
    if (v.skill_path) body.skill_path = v.skill_path;
    if (v.rename) body.rename = v.rename;
    await api("/api/skills/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    await loadSkills();
  });
});

// ---------- chat + invocation log ----------

function addChatMsg(role, text) {
  chatLog.appendChild(el("div", { class: `msg ${role}` }, [
    el("div", { class: "role", text: role }),
    el("div", { class: "content", text }),
  ]));
  chatLog.scrollTop = chatLog.scrollHeight;
}

function addExecEvent(ev) {
  const box = el("div", { class: `event ${ev.type}` });
  if (ev.type === "assistant_text") {
    box.appendChild(el("div", { class: "label", text: "assistant" }));
    box.appendChild(el("pre", { text: ev.text }));
  } else if (ev.type === "tool_call") {
    box.appendChild(el("div", { class: "label", text: `→ tool_call: ${ev.tool}` }));
    box.appendChild(el("pre", { text: JSON.stringify(ev.input, null, 2) }));
  } else if (ev.type === "tool_result") {
    box.appendChild(el("div", { class: "label", text: `← tool_result: ${ev.tool} (${ev.ms}ms)` }));
    box.appendChild(el("pre", { text: JSON.stringify(ev.output, null, 2) }));
  } else if (ev.type === "error") {
    box.appendChild(el("div", { class: "label", text: "error" }));
    box.appendChild(el("pre", { text: ev.text }));
  } else {
    return;
  }
  execLog.appendChild(box);
  execLog.scrollTop = execLog.scrollHeight;
}

async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text) return;
  chatInput.value = "";
  addChatMsg("user", text);

  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: text }),
  });
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({}));
    addChatMsg("assistant", `[error] ${body.detail || res.statusText}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalText = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    buffer = lines.pop();
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const ev = JSON.parse(line.slice(6));
      if (ev.type === "assistant_text") finalText = ev.text;
      if (ev.type === "done" || ev.type === "error") {
        if (ev.type === "error") finalText = `[error] ${ev.text}`;
        continue;
      }
      addExecEvent(ev);
    }
  }
  addChatMsg("assistant", finalText || "(no response)");
  loadSkills();
}

document.getElementById("btn-send").addEventListener("click", sendMessage);
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

document.getElementById("btn-reset").addEventListener("click", async () => {
  await api("/api/chat/reset", { method: "POST" });
  chatLog.innerHTML = "";
  execLog.innerHTML = "";
});

loadSkills();
