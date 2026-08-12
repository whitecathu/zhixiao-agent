// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { defineComponent, h, type PropType } from "vue";
import { describe, expect, it } from "vitest";

import ExecutionGraph from "./ExecutionGraph.vue";

interface StubNode {
  id: string;
  data: Record<string, unknown>;
}

const VueFlowStub = defineComponent({
  name: "VueFlow",
  props: {
    nodes: {
      type: Array as PropType<StubNode[]>,
      default: () => [],
    },
    edges: {
      type: Array as PropType<unknown[]>,
      default: () => [],
    },
  },
  emits: ["update:nodes", "update:edges"],
  setup(props, { slots }) {
    return () =>
      h(
        "div",
        { class: "vue-flow-stub" },
        props.nodes.map((node) =>
          slots["node-default"]?.({ data: node.data }),
        ),
      );
  },
});

describe("ExecutionGraph accessibility", () => {
  it("announces graph detail and renders node status as text", () => {
    const wrapper = mount(ExecutionGraph, {
      props: {
        events: [
          {
            event: "tool",
            data: {
              source_event: "tool_result",
              tool: "write_file",
              summary: "saved",
            },
          },
        ],
      },
      global: {
        stubs: {
          VueFlow: VueFlowStub,
          Background: true,
          Controls: true,
        },
      },
    });

    expect(wrapper.get('[role="region"]').attributes("aria-labelledby")).toBe(
      "execution-graph-title",
    );
    expect(wrapper.get(".graph-meta small").attributes("aria-live")).toBe("polite");
    expect(wrapper.get('[role="group"]').attributes("aria-label")).toBe(
      "任务执行阶段",
    );

    const active = wrapper.get('.exec-node[aria-current="step"]');
    expect(active.text()).toContain("状态：进行中");
    expect(active.attributes("aria-label")).toContain("执行，状态：进行中");
  });
});
