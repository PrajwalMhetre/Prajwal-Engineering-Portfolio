(() => {
  const existingGrid = document.querySelector(".page-work-grid");
  if (!existingGrid) return;

  const section = document.createElement("section");
  section.className = "live-projects";
  const heading = document.createElement("div");
  heading.className = "page-heading";
  const label = document.createElement("p");
  label.className = "label";
  label.textContent = "LIVE / PUBLISHED PROJECTS";
  const title = document.createElement("h2");
  title.textContent = "More engineering work.";
  heading.append(label, title);
  const grid = document.createElement("div");
  grid.className = "work-grid page-work-grid";
  const more = document.createElement("button");
  more.className = "btn";
  more.type = "button";
  more.textContent = "Load more projects";
  more.hidden = true;
  section.append(heading, grid, more);
  existingGrid.insertAdjacentElement("afterend", section);

  let cursor = null;
  async function loadProjects(append = false) {
    more.disabled = true;
    try {
      const params = new URLSearchParams({ limit: "12" });
      if (cursor) params.set("cursor", cursor);
      const response = await fetch(`/api/projects?${params}`);
      if (!response.ok) throw new Error("Published projects are temporarily unavailable.");
      const page = await response.json();
      if (!append) grid.replaceChildren();
      for (const project of page.items) {
        const href = project.demo_url || project.repository_url;
        const card = document.createElement(href ? "a" : "article");
        card.className = "work-card";
        if (href) {
          card.href = href;
          card.target = "_blank";
          card.rel = "noopener noreferrer";
        }
        if (project.image_path) {
          const image = document.createElement("img");
          image.src = `/api/projects/${encodeURIComponent(project.slug)}/image`;
          image.alt = `${project.title} project image`;
          image.loading = "lazy";
          card.append(image);
        }
        const category = document.createElement("small");
        category.textContent = project.category.toUpperCase();
        const name = document.createElement("h3");
        name.textContent = project.title;
        const summary = document.createElement("p");
        summary.textContent = project.summary;
        const stack = document.createElement("b");
        stack.textContent = project.tech_stack || project.slug;
        card.append(category, name, summary, stack);
        grid.append(card);
      }
      cursor = page.next_cursor;
      more.hidden = !cursor;
      if (!page.items.length && !append) section.hidden = true;
    } catch (error) {
      grid.replaceChildren();
      const status = document.createElement("p");
      status.className = "page-intro";
      status.textContent = error.message;
      grid.append(status);
      more.hidden = true;
    } finally {
      more.disabled = false;
    }
  }

  more.addEventListener("click", () => loadProjects(true));
  loadProjects();
})();
