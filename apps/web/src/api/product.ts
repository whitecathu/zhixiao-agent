import { request } from "@/utils/request";
import type { ObservabilitySummary, OnboardingConfig, OnboardingState } from "@/types";

export const observabilityApi = {
  summary: (window = "24h") =>
    request<ObservabilitySummary>({ method: "GET", url: "/observability/summary", params: { window } }),
};

export const onboardingApi = {
  state: () => request<OnboardingState>({ method: "GET", url: "/onboarding/me" }),
  complete: (stepId: string) =>
    request<OnboardingState>({ method: "POST", url: `/onboarding/me/steps/${stepId}/complete` }),
  skip: () => request<OnboardingState>({ method: "POST", url: "/onboarding/me/skip" }),
  replay: () => request<OnboardingState>({ method: "POST", url: "/onboarding/me/replay" }),
  config: () => request<OnboardingConfig>({ method: "GET", url: "/onboarding/config" }),
  updateConfig: (data: Pick<OnboardingConfig, "recommended_template" | "default_workflow_id">) =>
    request<OnboardingConfig>({ method: "PUT", url: "/onboarding/config", data }),
};
