import { request } from "@/utils/request";
import type { Knowledge, PageData, SearchHit } from "@/types";

export const knowledgeApi = {
  list: (params: { page: number; page_size: number; type?: string; category_path?: string }) =>
    request<PageData<Knowledge>>({ method: "GET", url: "/knowledge", params }),
  get: (id: number) => request<Knowledge>({ method: "GET", url: `/knowledge/${id}` }),
  update: (id: number, data: Partial<Knowledge>) =>
    request<Knowledge>({ method: "PUT", url: `/knowledge/${id}`, data }),
  delete: (id: number) => request({ method: "DELETE", url: `/knowledge/${id}` }),
  search: (data: {
    query: string; type?: string; tags?: string[]; category_path?: string;
    include_low_quality?: boolean; top_k?: number;
    page?: number; page_size?: number;
  }) => request<{ items: SearchHit[]; total: number }>({ method: "POST", url: "/knowledge/search", data }),
  tags: () => request<{ id: number; name: string }[]>({ method: "GET", url: "/knowledge/tags" }),
  categories: () =>
    request<{ id: number; parent_id?: number | null; name: string; path?: string | null }[]>(
      { method: "GET", url: "/knowledge/categories" },
    ),
};