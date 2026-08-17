import { describe, expect, it } from "vitest";

import {
  buildCronJobPayload,
  composeDeliver,
  cronJobHasExecutionContent,
  cronJobFormFromJob,
  extractDiscordChannelTarget,
  slugifyCronChannelName,
  splitCronList,
  splitDeliver,
  type CronJobFormState,
} from "./cron-job";
import type { CronJob } from "./api";

function form(overrides: Partial<CronJobFormState> = {}): CronJobFormState {
  return {
    name: "",
    prompt: "prompt",
    schedule: "every 1h",
    deliver: "local",
    discordChannelId: null,
    skills: [],
    provider: "",
    model: "",
    base_url: "",
    script: "",
    no_agent: false,
    context_from: "",
    continuity: false,
    enabled_toolsets: [],
    workdir: "",
    ...overrides,
  };
}

describe("splitCronList", () => {
  it("normalizes comma and newline separated cron list fields", () => {
    expect(splitCronList(" web, terminal\nfile ,, ")).toEqual([
      "web",
      "terminal",
      "file",
    ]);
  });
});

describe("buildCronJobPayload", () => {
  it("normalizes list fields and base URLs", () => {
    const payload = buildCronJobPayload(
      form({
        base_url: "https://example.invalid/v1/",
        enabled_toolsets: ["web", ""],
        context_from: "upstream-a\nupstream-b",
      }),
    );

    expect(payload).toMatchObject({
      base_url: "https://example.invalid/v1",
      context_from: ["upstream-a", "upstream-b"],
      enabled_toolsets: ["web"],
    });
  });

  it("stores continuity as the reserved self entry", () => {
    const payload = buildCronJobPayload(
      form({ continuity: true, context_from: "upstream-a" }),
    );

    expect(payload.context_from).toEqual(["upstream-a", "self"]);
  });

  it("continuity off strips any hand-typed self entry", () => {
    const payload = buildCronJobPayload(
      form({ continuity: false, context_from: "SELF\nupstream-a" }),
    );

    expect(payload.context_from).toEqual(["upstream-a"]);
  });

  it("keeps clear operations explicit for update payloads", () => {
    const payload = buildCronJobPayload(form({ schedule: "every 2h" }));

    expect(payload).toMatchObject({
      schedule: "every 2h",
      provider: null,
      model: null,
      base_url: null,
      script: null,
      no_agent: false,
      context_from: null,
      enabled_toolsets: null,
      workdir: null,
    });
  });
});

describe("cronJobHasExecutionContent", () => {
  it("treats a script as execution content for agent-backed cron jobs", () => {
    const payload = buildCronJobPayload(
      form({ prompt: "", skills: [], script: "collect-status.py" }),
    );

    expect(cronJobHasExecutionContent(payload)).toBe(true);
  });

  it("rejects payloads with no prompt, skills, or script", () => {
    const payload = buildCronJobPayload(form({ prompt: "", skills: [], script: "" }));

    expect(cronJobHasExecutionContent(payload)).toBe(false);
  });
});

describe("cronJobFormFromJob", () => {
  it("preserves schedule fallback and editable list fields", () => {
    const job: CronJob = {
      id: "abc",
      enabled: true,
      schedule_display: "every 1h",
      context_from: ["upstream-a", "upstream-b"],
      enabled_toolsets: ["web"],
    };

    expect(cronJobFormFromJob(job)).toMatchObject({
      schedule: "every 1h",
      context_from: "upstream-a\nupstream-b",
      continuity: false,
      enabled_toolsets: ["web"],
    });
  });

  it("splits the stored self entry into the continuity toggle", () => {
    const job: CronJob = {
      id: "abc",
      enabled: true,
      schedule_display: "every 1h",
      context_from: ["self", "upstream-a"],
    };

    expect(cronJobFormFromJob(job)).toMatchObject({
      context_from: "upstream-a",
      continuity: true,
    });
  });

  it("prefers one-shot run_at over the human display string", () => {
    const job: CronJob = {
      id: "once-job",
      enabled: true,
      schedule: {
        kind: "once",
        run_at: "2026-02-03T14:00:00+08:00",
      },
      schedule_display: "once at 2026-02-03 14:00",
    };

    expect(cronJobFormFromJob(job)).toMatchObject({
      schedule: "2026-02-03T14:00:00+08:00",
    });
  });
});

describe("splitDeliver", () => {
  it("splits comma-separated targets and drops empties", () => {
    expect(splitDeliver("local, discord:123 ,,origin")).toEqual([
      "local",
      "discord:123",
      "origin",
    ]);
    expect(splitDeliver("")).toEqual([]);
  });
});

describe("extractDiscordChannelTarget", () => {
  it("returns the channel id from a discord target", () => {
    expect(extractDiscordChannelTarget("local,discord:123")).toBe("123");
    expect(extractDiscordChannelTarget("discord:123")).toBe("123");
  });

  it("returns null when no discord target is present", () => {
    expect(extractDiscordChannelTarget("local,origin")).toBe(null);
    expect(extractDiscordChannelTarget("")).toBe(null);
    expect(extractDiscordChannelTarget("discord:")).toBe(null);
  });
});

describe("composeDeliver", () => {
  it("appends the Discord channel to local", () => {
    expect(composeDeliver("local", "123")).toBe("local,discord:123");
  });

  it("appends the Discord channel to origin", () => {
    expect(composeDeliver("origin", "123")).toBe("origin,discord:123");
  });

  it("strips only the discord target when toggled off", () => {
    expect(composeDeliver("local,discord:123", null)).toBe("local");
    expect(composeDeliver("origin,discord:123", null)).toBe("origin");
  });

  it("replaces a pre-existing discord target instead of duplicating it", () => {
    expect(composeDeliver("local,discord:111", "222")).toBe("local,discord:222");
  });

  it("falls back to local for an empty base", () => {
    expect(composeDeliver("", "123")).toBe("local,discord:123");
    expect(composeDeliver("", null)).toBe("local");
    expect(composeDeliver("discord:123", null)).toBe("local");
  });

  it("never emits duplicate or comma-dangling entries", () => {
    expect(composeDeliver("local,local,", null)).toBe("local");
    expect(composeDeliver("local,,discord:123", "123")).toBe("local,discord:123");
  });

  it("is idempotent", () => {
    const once = composeDeliver("local", "123");
    expect(composeDeliver(once, "123")).toBe(once);
    expect(composeDeliver(composeDeliver(once, "123"), "123")).toBe(once);
  });
});

describe("slugifyCronChannelName", () => {
  it("slugifies a job name into the cron channel name", () => {
    expect(slugifyCronChannelName("LM Studio Release Review & Upgrade Advisor")).toBe(
      "cron-lm-studio-release-review-upgrade-advisor",
    );
  });

  it("collapses dashes and strips unsafe characters", () => {
    expect(slugifyCronChannelName("  Weird   Name!! (v2) ")).toBe("cron-weird-name-v2");
    expect(slugifyCronChannelName("")).toBe("cron-");
  });
});

describe("buildCronJobPayload deliver composition", () => {
  it("appends the picked Discord channel to the base target", () => {
    const payload = buildCronJobPayload(form({ discordChannelId: "123" }));
    expect(payload.deliver).toBe("local,discord:123");
  });

  it("strips only the discord entry when the export is off", () => {
    const payload = buildCronJobPayload(
      form({ deliver: "origin,discord:123", discordChannelId: null }),
    );
    expect(payload.deliver).toBe("origin");
  });
});

describe("cronJobFormFromJob discord split", () => {
  it("seeds the picker from the base target and the toggle from discord:<id>", () => {
    const formState = cronJobFormFromJob({
      id: "abc",
      enabled: true,
      deliver: "origin,discord:123",
    });
    expect(formState.deliver).toBe("origin");
    expect(formState.discordChannelId).toBe("123");
  });

  it("defaults to local with no export when deliver is empty", () => {
    const formState = cronJobFormFromJob({ id: "abc", enabled: true });
    expect(formState.deliver).toBe("local");
    expect(formState.discordChannelId).toBe(null);
  });
});
