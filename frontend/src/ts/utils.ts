export function byId<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`Missing element: ${id}`);
  }
  return element as T;
}

export function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}

export function table(headers: string[], rows: string[][]): string {
  const headerHtml = headers.map((h) => `<th>${esc(h)}</th>`).join("");
  const bodyHtml = rows
    .map((row) => `<tr>${row.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`)
    .join("");
  return `<table><thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table>`;
}

export function status(message: string, { safe = false }: { safe?: boolean } = {}): string {
  const content = safe ? message : esc(message);
  return `<div class="status">${content}</div>`;
}

export function formatDate(dateString: string): string {
  if (!dateString) return "TBD";
  const date = new Date(dateString);
  if (isNaN(date.getTime())) return "TBD";
  return date.toLocaleString();
}

export function formatDateShort(dateString: string): string {
  if (!dateString) return "TBD";
  const date = new Date(dateString);
  if (isNaN(date.getTime())) return "TBD";
  return date.toLocaleDateString();
}

export interface InfiniteScrollOptions {
  scrollContainerId: string;
  sentinelId: string;
  statusId: string;
  batchSize: number;
  totalItems: number;
  onLoadMore: (start: number, end: number) => void;
}

export function setupInfiniteScroll(options: InfiniteScrollOptions): () => void {
  const { scrollContainerId, sentinelId, statusId, batchSize, totalItems, onLoadMore } = options;
  let currentIndex = batchSize; // Start after the initial batch
  
  const scrollContainer = document.getElementById(scrollContainerId);
  const sentinel = document.getElementById(sentinelId);
  const status = document.getElementById(statusId);
  
  if (!scrollContainer) {
    console.error(`Missing scroll container: ${scrollContainerId}`);
    return () => {};
  }
  
  if (!sentinel || !status) {
    console.error(`Missing sentinel (${sentinelId}) or status (${statusId}) element`);
    return () => {};
  }
  
  if (currentIndex >= totalItems) {
    status.textContent = "";
    return () => {};
  }
  
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting && currentIndex < totalItems) {
        const end = Math.min(currentIndex + batchSize, totalItems);
        status.textContent = "Loading more...";
        
        // Use setTimeout to avoid blocking the UI
        setTimeout(() => {
          onLoadMore(currentIndex, end);
          currentIndex = end;
          
          if (currentIndex >= totalItems) {
            status.textContent = "";
            observer.disconnect();
          } else {
            status.textContent = "";
          }
        }, 100);
      }
    });
  }, {
    root: scrollContainer,
    rootMargin: "100px",
    threshold: 0.1
  });
  
  observer.observe(sentinel);
  
  // Return cleanup function
  return () => observer.disconnect();
}

export function appendTableRows(tableId: string, rows: string[][]): void {
  const table = document.getElementById(tableId)?.querySelector("tbody");
  if (!table) {
    console.error(`Table body not found for ${tableId}`);
    return;
  }
  
  const rowsHtml = rows
    .map((row) => `<tr>${row.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`)
    .join("");
  
  table.insertAdjacentHTML("beforeend", rowsHtml);
}

/** Options for server-side paginated infinite scroll. */
export interface ServerPaginatedScrollOptions {
  scrollContainerId: string;
  sentinelId: string;
  statusId: string;
  pageSize: number;
  /** Total number of items (from the first page response). */
  totalItems: number;
  /** Async callback to fetch the next page and return rendered table rows. */
  fetchPage: (page: number) => Promise<string[][]>;
}

/**
 * Set up infinite scroll that fetches pages from the server on demand.
 * Starts at page 2 (page 1 is assumed already rendered).
 */
export function setupServerPaginatedScroll(options: ServerPaginatedScrollOptions): () => void {
  const { scrollContainerId, sentinelId, statusId, pageSize, totalItems, fetchPage } = options;
  let nextPage = 2;
  let loadedCount = pageSize;
  let loading = false;

  const scrollContainer = document.getElementById(scrollContainerId);
  const sentinel = document.getElementById(sentinelId);
  const statusEl = document.getElementById(statusId);

  if (!scrollContainer || !sentinel || !statusEl) {
    console.error(`Missing scroll elements for server-paginated scroll`);
    return () => {};
  }

  if (loadedCount >= totalItems) {
    statusEl.textContent = "";
    return () => {};
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting && loadedCount < totalItems && !loading) {
        loading = true;
        statusEl.textContent = "Loading more...";

        fetchPage(nextPage)
          .then((rows) => {
            appendTableRows(scrollContainerId.replace("-scroll-container", ""), rows);
            loadedCount += rows.length;
            nextPage++;
            loading = false;

            if (loadedCount >= totalItems || rows.length === 0) {
              statusEl.textContent = "";
              observer.disconnect();
            } else {
              statusEl.textContent = "";
            }
          })
          .catch((err) => {
            console.error("Failed to load page:", err);
            statusEl.textContent = "Failed to load more items.";
            loading = false;
          });
      }
    });
  }, {
    root: scrollContainer,
    rootMargin: "100px",
    threshold: 0.1,
  });

  observer.observe(sentinel);
  return () => observer.disconnect();
}
