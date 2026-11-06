const $ = selector => document.querySelector(selector);
const loginPanel = $("#login-panel");
const dashboard = $("#dashboard");
const loginForm = $("#login-form");
const loginError = $("#login-error");
const notice = $("#notice");
const projectForm = $("#project-form");
let messageCursor = null;
let projectCursor = null;
let editingProject = null;
let editingImagePath = null;
let refreshPromise = null;

$("#year").textContent = new Date().getFullYear();

function message(text, bad = false) {
  notice.textContent = text;
  notice.className = "notice show" + (bad ? " bad" : "");
  setTimeout(() => notice.classList.remove("show"), 5000);
}

async function api(path, options = {}, retried = false) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers
  });
  if (response.status === 401 && !retried && !path.startsWith("/api/auth/")) {
    try {
      if (!refreshPromise) {
        refreshPromise = fetch("/api/auth/refresh", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: "{}"
        }).then(refresh => {
          if (!refresh.ok) throw new Error("Session expired");
        }).finally(() => {
          refreshPromise = null;
        });
      }
      await refreshPromise;
      return api(path, options, true);
    } catch {
      showLogin();
    }
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    // Empty responses, including project deletion, are expected.
  }
  if (!response.ok) {
    if (response.status === 401) showLogin();
    throw new Error(data?.detail || `Request failed (${response.status})`);
  }
  return data;
}

function showLogin() {
  dashboard.hidden = true;
  loginPanel.hidden = false;
  $("#logout").hidden = true;
  $("#session-label").textContent = "ADMIN CONSOLE";
}

function showDashboard(user) {
  loginPanel.hidden = true;
  dashboard.hidden = false;
  $("#logout").hidden = false;
  $("#session-label").textContent = "AUTHENTICATED";
  $("#admin-email").textContent = user.email || "";
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function addButton(container, text, callback, className = "button ghost") {
  const button = el("button", className, text);
  button.type = "button";
  button.addEventListener("click", callback);
  container.append(button);
  return button;
}

function renderMessages(rows, append = false) {
  const root = $("#messages");
  if (!append) root.replaceChildren();
  if (!rows.length && !append) {
    root.append(el("p", "muted", "No messages found."));
    return;
  }
  for (const row of rows) {
    const card = el("article", "message");
    const top = el("div", "message-top");
    const left = el("div");
    left.append(
      el("strong", "", row.name),
      el("div", "meta", `${row.email} · ${new Date(row.created_at).toLocaleString()}`)
    );
    top.append(left, el("span", "tag", row.status));
    card.append(top, el("h3", "", row.subject), el("p", "", row.message));

    const actions = el("div", "message-actions");
    const select = el("select");
    for (const status of ["new", "read", "replied", "archived", "spam"]) {
      const option = el("option", "", status);
      option.value = status;
      option.selected = status === row.status;
      select.append(option);
    }
    const save = addButton(actions, "Update status", async () => {
      save.disabled = true;
      try {
        await api(`/api/admin/messages/${encodeURIComponent(row.id)}`, {
          method: "PATCH",
          body: JSON.stringify({ status: select.value })
        });
        message("Message status updated.");
        await load();
      } catch (error) {
        message(error.message, true);
      } finally {
        save.disabled = false;
      }
    });
    actions.prepend(select);
    card.append(actions);
    root.append(card);
  }
}

function renderProjects(rows, append = false) {
  const root = $("#project-list");
  if (!append) root.replaceChildren();
  if (!rows.length && !append) {
    root.append(el("p", "muted", "No projects have been added."));
    return;
  }
  for (const project of rows) {
    const card = el("article", "message project-row");
    if (project.image_path) {
      const image = el("img", "project-thumbnail");
      image.src = `/api/projects/${encodeURIComponent(project.slug)}/image`;
      image.alt = `${project.title} project image`;
      image.loading = "lazy";
      card.append(image);
    }
    card.append(
      el("div", "project-meta", `${project.category.toUpperCase()} · ${project.published ? "PUBLISHED" : "DRAFT"}`),
      el("h3", "", project.title),
      el("p", "", project.summary),
      el("div", "project-meta", `/${project.slug} · ${project.view_count || 0} views`)
    );
    const actions = el("div", "project-actions");
    addButton(actions, "Edit", () => beginProjectEdit(project));
    addButton(actions, "Delete", async () => {
      if (!window.confirm(`Delete "${project.title}"? This cannot be undone.`)) return;
      try {
        await api(`/api/admin/projects/${encodeURIComponent(project.id)}`, { method: "DELETE" });
        message("Project deleted.");
        if (editingProject === project.id) resetProjectForm();
        await load();
      } catch (error) {
        message(error.message, true);
      }
    });
    card.append(actions);
    root.append(card);
  }
}

function beginProjectEdit(project) {
  editingProject = project.id;
  editingImagePath = project.image_path || null;
  projectForm.elements.title.value = project.title;
  projectForm.elements.slug.value = project.slug;
  projectForm.elements.slug.disabled = true;
  projectForm.elements.category.value = project.category;
  projectForm.elements.summary.value = project.summary;
  projectForm.elements.description.value = project.description || "";
  projectForm.elements.tech_stack.value = project.tech_stack || "";
  projectForm.elements.repository_url.value = project.repository_url || "";
  projectForm.elements.demo_url.value = project.demo_url || "";
  projectForm.elements.featured.checked = project.featured;
  projectForm.elements.published.checked = project.published;
  $("#project-form-title").textContent = "Edit project";
  $("#project-submit").textContent = "Update project ↗";
  $("#cancel-project-edit").hidden = false;
  projectForm.scrollIntoView({ behavior: "smooth", block: "start" });
}

function resetProjectForm() {
  editingProject = null;
  editingImagePath = null;
  projectForm.reset();
  projectForm.elements.slug.disabled = false;
  projectForm.elements.published.checked = true;
  $("#project-form-title").textContent = "Add a project";
  $("#project-submit").textContent = "Save project ↗";
  $("#cancel-project-edit").hidden = true;
}

async function load() {
  const filter = $("#message-filter").value;
  const [analytics, messages, projects] = await Promise.all([
    api("/api/admin/analytics"),
    api(`/api/admin/messages?limit=50${filter ? `&status=${encodeURIComponent(filter)}` : ""}`),
    api("/api/admin/projects?limit=50")
  ]);
  $("#metric-total").textContent = analytics.total_contact_messages;
  $("#metric-new").textContent = analytics.new_messages;
  $("#metric-projects").textContent = analytics.total_projects;
  renderMessages(messages.items);
  renderProjects(projects.items);
  messageCursor = messages.next_cursor;
  projectCursor = projects.next_cursor;
  $("#load-more-messages").hidden = !messageCursor;
  $("#load-more-projects").hidden = !projectCursor;

  const views = $("#views");
  views.replaceChildren();
  if (!analytics.project_views.length) {
    views.append(el("p", "muted", "No project views recorded yet."));
  } else {
    for (const item of analytics.project_views) {
      const pill = el("div", "view-pill");
      pill.append(el("b", "", String(item.views)), el("span", "", item.slug));
      views.append(pill);
    }
  }
}

loginForm.addEventListener("submit", async event => {
  event.preventDefault();
  loginError.textContent = "";
  const button = loginForm.querySelector("button");
  button.disabled = true;
  const formData = new FormData(loginForm);
  try {
    const user = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: formData.get("email"), password: formData.get("password") })
    });
    showDashboard(user);
    loginForm.reset();
    await load();
  } catch (error) {
    loginError.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

$("#logout").addEventListener("click", async () => {
  try {
    await api("/api/auth/logout", { method: "POST", body: "{}" });
    showLogin();
    message("Signed out.");
  } catch (error) {
    message(error.message, true);
  }
});

$("#refresh").addEventListener("click", async () => {
  try {
    await load();
    message("Dashboard refreshed.");
  } catch (error) {
    message(error.message, true);
  }
});

$("#message-filter").addEventListener("change", () => load().catch(error => message(error.message, true)));

$("#load-more-messages").addEventListener("click", async event => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const filter = $("#message-filter").value;
    const result = await api(`/api/admin/messages?limit=50&cursor=${encodeURIComponent(messageCursor)}${filter ? `&status=${encodeURIComponent(filter)}` : ""}`);
    renderMessages(result.items, true);
    messageCursor = result.next_cursor;
    button.hidden = !messageCursor;
  } catch (error) {
    message(error.message, true);
  } finally {
    button.disabled = false;
  }
});

$("#load-more-projects").addEventListener("click", async event => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const result = await api(`/api/admin/projects?limit=50&cursor=${encodeURIComponent(projectCursor)}`);
    renderProjects(result.items, true);
    projectCursor = result.next_cursor;
    button.hidden = !projectCursor;
  } catch (error) {
    message(error.message, true);
  } finally {
    button.disabled = false;
  }
});

$("#cancel-project-edit").addEventListener("click", resetProjectForm);

projectForm.addEventListener("submit", async event => {
  event.preventDefault();
  const button = $("#project-submit");
  button.disabled = true;
  const formData = new FormData(projectForm);
  const payload = {
    title: formData.get("title"),
    category: formData.get("category"),
    summary: formData.get("summary"),
    description: formData.get("description"),
    tech_stack: formData.get("tech_stack"),
    repository_url: formData.get("repository_url") || null,
    demo_url: formData.get("demo_url") || null,
    image_path: editingImagePath,
    featured: formData.has("featured"),
    published: formData.has("published")
  };
  const updating = Boolean(editingProject);
  if (!updating) payload.slug = formData.get("slug");
  try {
    const image = formData.get("image");
    if (image instanceof File && image.size) {
      button.textContent = "Uploading image…";
      const uploadData = new FormData();
      uploadData.append("file", image);
      const uploaded = await api("/api/admin/uploads", {
        method: "POST",
        body: uploadData
      });
      payload.image_path = uploaded.path;
    }
    button.textContent = updating ? "Updating project…" : "Saving project…";
    await api(
      updating
        ? `/api/admin/projects/${encodeURIComponent(editingProject)}`
        : "/api/admin/projects",
      {
        method: updating ? "PUT" : "POST",
        body: JSON.stringify(payload)
      }
    );
    resetProjectForm();
    message(updating ? "Project updated." : "Project created.");
    await load();
  } catch (error) {
    message(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = editingProject ? "Update project ↗" : "Save project ↗";
  }
});

$("#load-more-messages").hidden = true;
$("#load-more-projects").hidden = true;
api("/api/admin/me").then(async user => {
  showDashboard(user);
  await load();
}).catch(error => {
  showLogin();
  if (!String(error.message).includes("(401)")) loginError.textContent = error.message;
});
