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
  const [showPassword, setShowPassword] = useState(false);

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
      navigate("/accounts");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "登录失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthFrame title="欢迎回来" subtitle="用邮箱进入。登录后先看到网盘账号。">
      <form className="space-y-4" onSubmit={onSubmit}>
        <label className="block text-[13px] font-medium text-ink/80">
          邮箱
          <input name="email" type="email" required autoComplete="email" placeholder="you@example.com" className="field" />
        </label>
        <label className="block text-[13px] font-medium text-ink/80">
          密码
          <span className="relative mt-2 block">
            <input
              name="password"
              type={showPassword ? "text" : "password"}
              required
              minLength={8}
              autoComplete="current-password"
              placeholder="至少 8 位"
              className="field mt-0 pr-14"
            />
            <button
              type="button"
              className="absolute top-1/2 right-3 -translate-y-1/2 text-[12px] text-ink/45 hover:text-ink"
              onClick={() => setShowPassword((value) => !value)}
            >
              {showPassword ? "隐藏" : "显示"}
            </button>
          </span>
        </label>
        {error ? <p className="alert">{error}</p> : null}
        <button type="submit" disabled={pending} className="btn btn-primary w-full">
          {pending ? "登录中" : "登录"}
        </button>
      </form>
      <p className="mt-6 text-center text-sm text-ink/55">
        没有账号？{" "}
        <Link to="/register" className="font-bold text-primary-dark hover:text-primary">
          注册
        </Link>
      </p>
    </AuthFrame>
  );
}
