import { Button, Form, Input, Typography, message } from "antd";
import { Link, useNavigate } from "react-router-dom";
import { api, type User } from "../api";

type RegisterPageProps = {
  onAuthenticated: (user: User) => void;
};

export default function RegisterPage({ onAuthenticated }: RegisterPageProps) {
  const navigate = useNavigate();
  return (
    <Form
      style={{ maxWidth: 360, margin: "80px auto" }}
      onFinish={async (values: { email: string; password: string }) => {
        try {
          const user = await api.register(values.email, values.password);
          onAuthenticated(user);
          navigate("/");
        } catch (error) {
          message.error(error instanceof Error ? error.message : "注册失败");
        }
      }}
    >
      <Typography.Title level={3}>注册</Typography.Title>
      <Form.Item name="email" rules={[{ required: true, type: "email" }]}>
        <Input placeholder="邮箱" />
      </Form.Item>
      <Form.Item name="password" rules={[{ required: true, min: 8 }]}>
        <Input.Password placeholder="至少 8 位密码" />
      </Form.Item>
      <Button type="primary" htmlType="submit" block>
        注册
      </Button>
      <Link to="/login">已有账号</Link>
    </Form>
  );
}
