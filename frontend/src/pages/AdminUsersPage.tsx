import { DatePicker, Select, Space, Table, message } from "antd";
import type { Dayjs } from "dayjs";
import { useEffect, useState } from "react";
import { api, type User } from "../api";

export default function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [expiry, setExpiry] = useState<Record<number, Dayjs | null>>({});

  async function load() {
    setUsers(await api.users());
  }

  useEffect(() => {
    load().catch((error: Error) => message.error(error.message));
  }, []);

  return (
    <Table
      rowKey="id"
      dataSource={users}
      columns={[
        { title: "邮箱", dataIndex: "email" },
        { title: "角色", dataIndex: "role" },
        { title: "等级", dataIndex: "plan" },
        { title: "当前有效", dataIndex: "effective_plan" },
        {
          title: "调整",
          render: (_, user) => (
            <Space>
              <DatePicker
                showTime
                onChange={(value) => setExpiry({ ...expiry, [user.id]: value })}
              />
              <Select
                defaultValue={user.plan}
                style={{ width: 100 }}
                options={[
                  { value: "free", label: "免费" },
                  { value: "paid", label: "付费" },
                ]}
                onChange={async (plan) => {
                  try {
                    const selected = expiry[user.id];
                    await api.updatePlan(user.id, plan, plan === "paid" ? selected?.toISOString() ?? null : null);
                    await load();
                  } catch (error) {
                    message.error(error instanceof Error ? error.message : "保存失败");
                  }
                }}
              />
            </Space>
          ),
        },
      ]}
    />
  );
}
