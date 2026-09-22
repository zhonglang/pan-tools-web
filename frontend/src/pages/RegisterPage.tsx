import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type User } from "../api";
import AuthFrame from "../components/AuthFrame";

type RegisterPageProps = {
  onAuthenticated: (user: User) => void;
};

export default function RegisterPage({ onAuthenticated }: RegisterPageProps) {
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
      const user = await api.register(email, password);
      onAuthenticated(user);
      navigate("/");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "注册失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthFrame title="创建账号" subtitle="注册后默认为免费会员。付费等级由管理员开通。">
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
            maxLength={128}
            autoComplete="new-password"
            placeholder="8 到 128 位"
            className="mt-2 w-full rounded-2xl border border-line bg-canvas px-4 py-3 text-sm outline-none transition duration-200 placeholder:text-ink/35 focus:border-primary focus:bg-white"
          />
        </label>
        {error ? <p className="rounded-2xl bg-red-50 px-4 py-3 text-sm text-danger">{error}</p> : null}
        <button
          type="submit"
          disabled={pending}
          className="w-full rounded-2xl bg-accent px-4 py-3 text-sm font-semibold text-white transition duration-200 hover:bg-orange-700 disabled:cursor-wait disabled:opacity-70"
        >
          {pending ? "正在创建" : "注册并进入"}
        </button>
      </form>
      <p className="mt-6 text-sm text-ink/65">
        已有账号？{" "}
        <Link to="/login" className="font-semibold text-primary-dark hover:text-primary">
          去登录
        </Link>
      </p>
    </AuthFrame>
  );
}
