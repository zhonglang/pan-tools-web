import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type User } from "../api";
import AuthFrame from "../components/AuthFrame";

type LoginPageProps = {
  onAuthenticated: (user: User) => void;
};

export default function LoginPage({ onAuthenticated }: LoginPageProps) {
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "");
    const password = String(form.get("password") ?? "");
    setPending(true);
    setError("");
    try {
      const user = await api.login(email, password);
      onAuthenticated(user);
      navigate(user.role === "admin" ? "/admin/users" : "/");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "登录失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthFrame title="欢迎回来" subtitle="使用邮箱进入工作台。管理员会直接进入会员管理。">
      <form className="space-y-4" onSubmit={onSubmit}>
        <label className="block text-sm font-medium text-ink">
          邮箱
          <input
            name="email"
            type="email"
            required
            autoComplete="email"
            placeholder="you@example.com"
            className="mt-2 w-full rounded-2xl border border-line bg-canvas px-4 py-3 text-sm outline-none transition duration-200 placeholder:text-ink/35 focus:border-primary focus:bg-white"
          />
        </label>
        <label className="block text-sm font-medium text-ink">
          密码
          <input
            name="password"
            type="password"
            required
            minLength={8}
            autoComplete="current-password"
            placeholder="至少 8 位"
            className="mt-2 w-full rounded-2xl border border-line bg-canvas px-4 py-3 text-sm outline-none transition duration-200 placeholder:text-ink/35 focus:border-primary focus:bg-white"
          />
        </label>
        {error ? <p className="rounded-2xl bg-red-50 px-4 py-3 text-sm text-danger">{error}</p> : null}
        <button
          type="submit"
          disabled={pending}
          className="w-full rounded-2xl bg-accent px-4 py-3 text-sm font-semibold text-white transition duration-200 hover:bg-orange-700 disabled:cursor-wait disabled:opacity-70"
        >
          {pending ? "正在登录" : "进入工作台"}
        </button>
      </form>
      <p className="mt-6 text-sm text-ink/65">
        还没有账号？{" "}
        <Link to="/register" className="font-semibold text-primary-dark hover:text-primary">
          创建账号
        </Link>
      </p>
    </AuthFrame>
  );
}
