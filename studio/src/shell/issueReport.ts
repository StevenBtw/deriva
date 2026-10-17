/** The "Report issue" link: a new GitHub bug report pre-filled with what this install knows about itself. */

export const GITHUB_URL = "https://github.com/StevenBtw/deriva";

/** What the studio knows at runtime: the server reports the OS and Python, the browser reports itself. */
export type IssueEnvironment = {
  version?: string;
  /** Which install the reporter runs: deriva-dev (with benchmarking) or deriva-studio. */
  install?: string;
  os?: string;
  python?: string;
  browser?: string;
};

/** A new bug report on GitHub with the environment pre-filled in the body.
 *
 * GitHub ignores the `body` parameter when `template` is set, so the studio builds the issue text
 * itself, mirroring `.github/ISSUE_TEMPLATE/studio_bug.md` (that template serves reporters who
 * start from the GitHub UI). Only what is known goes in; empty values are left out.
 */
export function newIssueUrl(environment: IssueEnvironment): string {
  const body = [
    "**Describe the bug**",
    "A clear description of the bug.",
    "",
    "**To Reproduce**",
    "Steps to reproduce the behavior.",
    "",
    "**Expected behavior**",
    "What you expected to happen.",
    "",
    "**Screenshots**",
    "If applicable, add screenshots.",
    "",
    "**Environment**",
  ];
  const known: [string, string | undefined][] = [
    ["Deriva version", environment.version],
    ["Install", environment.install],
    ["OS", environment.os],
    ["Python", environment.python],
    ["Browser", environment.browser],
  ];
  for (const [label, value] of known) {
    if (value) body.push(`- ${label}: ${value}`);
  }
  const params = new URLSearchParams({ labels: "bug", title: "[BUG] ", body: body.join("\n") });
  return `${GITHUB_URL}/issues/new?${params}`;
}

/** The Chromium "high entropy" user agent hints; not in every TS lib version, so typed here. */
type UserAgentData = { platform?: string; brands?: { brand: string; version: string }[] };

function userAgentData(): UserAgentData | undefined {
  return (navigator as { userAgentData?: UserAgentData }).userAgentData;
}

/** The OS from the browser's hints ("unknown" when the user agent gives no clue). */
export function detectOs(): string {
  const platform = userAgentData()?.platform;
  if (platform) return platform;
  const ua = navigator.userAgent;
  if (/windows/i.test(ua)) return "Windows";
  if (/mac os|macintosh/i.test(ua)) return "macOS";
  if (/android/i.test(ua)) return "Android";
  if (/linux/i.test(ua)) return "Linux";
  return "unknown";
}

/** The browser with its version, from the high entropy hints or the user agent ("unknown" as a last resort). */
export function detectBrowser(): string {
  const brands = userAgentData()?.brands?.filter(({ brand }) => !/not.?a.?brand|chromium/i.test(brand));
  if (brands?.length) return `${brands[0].brand} ${brands[0].version}`;
  const ua = navigator.userAgent;
  const edge = /Edg\/([\d.]+)/.exec(ua);
  if (edge) return `Edge ${edge[1]}`;
  const firefox = /Firefox\/([\d.]+)/.exec(ua);
  if (firefox) return `Firefox ${firefox[1]}`;
  // Chrome on iOS writes CriOS, followed by the Safari tokens
  const chrome = /(?:Chrome|CriOS)\/([\d.]+)/.exec(ua);
  if (chrome) return `Chrome ${chrome[1]}`;
  const safari = /Version\/([\d.]+).*Safari/.exec(ua);
  if (safari) return `Safari ${safari[1]}`;
  return "unknown";
}
