import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import type { User } from "../api";
import BrandMark from "./BrandMark";

const SIDEBAR_KEY = "pan-tools.sidebar-collapsed";

const items = [
  { to: "/accounts", label: "网盘账号", end: false, icon: "cloud" },
  { to: "/transfer", label: "转存分享", end: false, icon: "folder" },
  { to: "/library", label: "资源库", end: false, icon: "library" },
  { to: "/stats", label: "数据概览", end: false, icon: "chart" },
  { to: "/jobs", label: "执行记录", end: false, icon: "list" },
  { to: "/downloads", label: "下载记录", end: false, icon: "download" },
  { to: "/settings", label: "系统配置", end: false, icon: "gear" },
] as const;

function navClass(active: boolean, collapsed: boolean) {
  return `flex h-10 w-full items-center gap-2.5 rounded-xl text-sm font-semibold ${
    collapsed ? "justify-center px-0" : "px-2.5"
  } ${active ? "bg-primary text-white" : "text-ink/70 hover:bg-muted hover:text-ink"}`;
}

function loadCollapsed() {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === "1";
  } catch {
    return false;
  }
}

export default function AppShell({
  user,
  onLogout,
  children,
}: {
  user: User;
  onLogout: () => void;
  children: ReactNode;
}) {
  const path = useLocation().pathname;
  const bleed = path === "/transfer";
  const wide = path === "/stats";
  const initial = user.email.slice(0, 1).toUpperCase();
  const [collapsed, setCollapsed] = useState(loadCollapsed);

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  return (
    <div
      className={`min-h-dvh bg-canvas lg:grid ${
        collapsed ? "lg:grid-cols-[72px_minmax(0,1fr)]" : "lg:grid-cols-[232px_minmax(0,1fr)]"
      }`}
    >
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-white focus:px-3 focus:py-2 focus:text-sm focus:font-semibold focus:text-ink"
      >
        跳到主要内容
      </a>
      <aside className="sticky top-0 hidden h-dvh flex-col border-r border-line bg-white lg:flex">
        <div className={`pb-2 pt-5 ${collapsed ? "px-3" : "px-5"}`}>
          <BrandMark compact={collapsed} />
        </div>
        <nav className={`mt-4 flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto ${collapsed ? "px-2" : "px-3"}`} aria-label="主导航">
          {collapsed ? null : <p className="mb-1 px-2.5 text-[12px] font-semibold text-ink/40">菜单</p>}
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              title={collapsed ? item.label : undefined}
              className={({ isActive }) => navClass(isActive, collapsed)}
            >
              <NavIcon name={item.icon} />
              {collapsed ? <span className="sr-only">{item.label}</span> : <span className="truncate">{item.label}</span>}
            </NavLink>
          ))}
          {user.role === "admin" ? (
            <NavLink
              to="/admin/users"
              title={collapsed ? "会员管理" : undefined}
              className={({ isActive }) => navClass(isActive, collapsed)}
            >
              <NavIcon name="users" />
              {collapsed ? <span className="sr-only">会员管理</span> : <span className="truncate">会员管理</span>}
            </NavLink>
          ) : null}
        </nav>
        <div className={`border-t border-line ${collapsed ? "p-2" : "p-3"}`}>
          <NavLink
            to="/profile"
            title={collapsed ? user.email : undefined}
            className={({ isActive }) =>
              `flex items-center rounded-xl ${collapsed ? "justify-center px-0 py-2" : "gap-2.5 px-2 py-2"} ${
                isActive ? "bg-muted" : "hover:bg-muted"
              }`
            }
          >
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary/10 text-xs font-bold text-primary-dark">
              {initial}
            </span>
            {collapsed ? null : (
              <span className="min-w-0">
                <span className="block truncate text-[13px] font-semibold text-ink">{user.email}</span>
                <span className="block text-[11px] text-ink/45">
                  {user.role === "admin" ? "管理员" : user.effective_plan === "paid" ? "付费用户" : "普通用户"}
                </span>
              </span>
            )}
          </NavLink>
          <button
            type="button"
            onClick={onLogout}
            title={collapsed ? "退出登录" : undefined}
            className={`mt-1 flex h-10 w-full items-center rounded-xl text-sm font-semibold text-ink/60 hover:bg-muted hover:text-ink ${
              collapsed ? "justify-center px-0" : "px-2.5"
            }`}
          >
            {collapsed ? (
              <svg width="16" height="16" viewBox="0 0 18 18" fill="none" aria-hidden="true">
                <path
                  d="M7 3.5H4.5A1.5 1.5 0 0 0 3 5v8a1.5 1.5 0 0 0 1.5 1.5H7M11.5 12.5 15 9m0 0-3.5-3.5M15 9H7"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            ) : (
              "退出登录"
            )}
            {collapsed ? <span className="sr-only">退出登录</span> : null}
          </button>
          <button
            type="button"
            onClick={() => setCollapsed((value) => !value)}
            aria-expanded={!collapsed}
            aria-label={collapsed ? "展开导航" : "收起导航"}
            className={`mt-1 flex h-10 w-full items-center rounded-xl text-sm font-semibold text-ink/60 hover:bg-muted hover:text-ink ${
              collapsed ? "justify-center px-0" : "gap-2 px-2.5"
            }`}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 18 18"
              fill="none"
              aria-hidden="true"
              className={collapsed ? "rotate-180" : ""}
            >
              <path d="M11 4.5 6.5 9 11 13.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {collapsed ? null : <span>收起菜单</span>}
          </button>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-30 border-b border-line bg-white lg:hidden">
          <div className="flex items-center justify-between px-4 py-3">
            <BrandMark />
            <div className="flex items-center gap-3">
              <NavLink to="/profile" className="max-w-[46vw] truncate text-[13px] font-semibold text-ink">
                {user.email}
              </NavLink>
              <button type="button" onClick={onLogout} className="text-[13px] font-medium text-ink/60">
                退出
              </button>
            </div>
          </div>
          <nav className="flex gap-1 overflow-x-auto px-3 pb-2">
            {items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `shrink-0 rounded-full px-3 py-1.5 text-[13px] font-medium ${
                    isActive ? "bg-primary text-white" : "text-ink/60"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
            {user.role === "admin" ? (
              <NavLink
                to="/admin/users"
                className={({ isActive }) =>
                  `shrink-0 rounded-full px-3 py-1.5 text-[13px] font-medium ${
                    isActive ? "bg-primary text-white" : "text-ink/60"
                  }`
                }
              >
                会员
              </NavLink>
            ) : null}
          </nav>
        </header>
        <main
          id="main"
          className={
            bleed
              ? "min-h-[calc(100dvh-6.5rem)] lg:h-dvh lg:min-h-0"
              : wide
                ? "mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8"
                : "mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8"
          }
        >
          {children}
        </main>
      </div>
    </div>
  );
}

function NavIcon({ name }: { name: "cloud" | "folder" | "library" | "chart" | "list" | "download" | "gear" | "users" }) {
  const common = { width: 16, height: 16, viewBox: "0 0 18 18", fill: "none", "aria-hidden": true as const };
  if (name === "cloud") {
    return (
      <svg {...common}>
        <path
          d="M5 13.5h7.2a2.8 2.8 0 0 0 .4-5.6 3.6 3.6 0 0 0-6.9 1.1A2.3 2.3 0 0 0 5 13.5Z"
          stroke="currentColor"
          strokeWidth="1.5"
        />
      </svg>
    );
  }
  if (name === "folder") {
    return (
      <svg {...common}>
        <path
          d="M2.5 5.5A1.5 1.5 0 0 1 4 4h3l1.5 1.5H14A1.5 1.5 0 0 1 15.5 7v6a1.5 1.5 0 0 1-1.5 1.5H4A1.5 1.5 0 0 1 2.5 13v-7.5Z"
          stroke="currentColor"
          strokeWidth="1.5"
        />
      </svg>
    );
  }
  if (name === "library") {
    return (
      <svg {...common}>
        <path
          d="M3.5 4.5h4.2c.6 0 1.2.2 1.6.6L9 5.8l-.3-.7c.4-.4 1-.6 1.6-.6h4.2v9H10c-.6 0-1.1.2-1.5.6-.4-.4-.9-.6-1.5-.6H3.5v-9Z"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  if (name === "chart") {
    return (
      <svg {...common}>
        <path d="M4 14.5V9M9 14.5V4M14 14.5v-3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }
  if (name === "list") {
    return (
      <svg {...common}>
        <path d="M6 4.5h9M6 9h9M6 13.5h9M3 4.5h.01M3 9h.01M3 13.5h.01" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }
  if (name === "gear") {
    return (
      <svg {...common}>
        <path
          d="M9 11.2a2.2 2.2 0 1 0 0-4.4 2.2 2.2 0 0 0 0 4.4ZM9 2.8v1.4M9 13.8v1.4M3.4 5.6l1.2.7M13.4 11.7l1.2.7M3.4 12.4l1.2-.7M13.4 6.3l1.2-.7"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    );
  }
  if (name === "download") {
    return (
      <svg {...common}>
        <path
          d="M9 3v8m0 0 3-3m-3 3L6 8M3.5 13.5v.5A1.5 1.5 0 0 0 5 15.5h8a1.5 1.5 0 0 0 1.5-1.5v-.5"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path
        d="M6.2 8.2a2.2 2.2 0 1 0 0-4.4 2.2 2.2 0 0 0 0 4.4ZM12.2 7.4a1.8 1.8 0 1 0 0-3.6 1.8 1.8 0 0 0 0 3.6ZM3.2 14.2c.4-1.8 1.8-2.8 3-2.8s2.6 1 3 2.8M11 11.6c.8-.2 1.7.1 2.3.8.6.6.8 1.3.8 1.8"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
