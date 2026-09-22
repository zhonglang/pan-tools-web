import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import type { User } from "../api";
import BrandMark from "./BrandMark";

function navClass(active: boolean) {
  return `rounded-xl px-3 py-2.5 text-sm font-medium transition-colors duration-200 ${
    active ? "bg-white text-ink shadow-sm" : "text-white/75 hover:bg-white/10 hover:text-white"
  }`;
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
  return (
    <div className="min-h-screen bg-canvas md:grid md:grid-cols-[248px_minmax(0,1fr)]">
      <aside className="bg-ink text-white md:min-h-screen md:px-4 md:py-6">
        <div className="flex items-center justify-between px-4 py-4 md:block md:px-2">
          <BrandMark light />
        </div>
        <nav className="flex gap-2 overflow-x-auto px-4 pb-4 md:mt-8 md:block md:space-y-1 md:px-2 md:pb-0">
          <NavLink to="/" end className={({ isActive }) => navClass(isActive)}>
            工作台
          </NavLink>
          <NavLink to="/accounts" className={({ isActive }) => navClass(isActive)}>
            网盘账号
          </NavLink>
          <NavLink to="/transfer" className={({ isActive }) => navClass(isActive)}>
            批量转存
          </NavLink>
          {user.role === "admin" ? (
            <NavLink to="/admin/users" className={({ isActive }) => navClass(isActive)}>
              会员管理
            </NavLink>
          ) : null}
        </nav>
      </aside>
      <div className="min-w-0">
        <header className="flex items-center justify-between border-b border-line bg-white/80 px-5 py-4 backdrop-blur md:px-8">
          <div>
            <div className="text-sm font-medium text-ink">{user.email}</div>
            <div className="text-xs text-ink/55">{user.role === "admin" ? "管理员" : "会员用户"}</div>
          </div>
          <button
            type="button"
            onClick={onLogout}
            className="rounded-full border border-line bg-white px-4 py-2 text-sm font-medium text-ink transition-colors duration-200 hover:border-primary hover:text-primary-dark"
          >
            退出
          </button>
        </header>
        <main className="px-5 py-6 md:px-8 md:py-8">{children}</main>
      </div>
    </div>
  );
}
