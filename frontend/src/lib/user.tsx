import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { currentUser } from "./api";

export const ROLE_OF: Record<string, "REQUESTER" | "BUYER" | "PROCUREMENT_ADMIN"> = {
  Asha: "REQUESTER",
  Rahul: "BUYER",
  Meera: "PROCUREMENT_ADMIN",
};
export const ROLE_LABEL = { REQUESTER: "Requester", BUYER: "Buyer", PROCUREMENT_ADMIN: "Procurement admin" } as const;

interface Ctx {
  user: string;
  role: "REQUESTER" | "BUYER" | "PROCUREMENT_ADMIN";
  setUser: (name: string) => void;
}

const UserCtx = createContext<Ctx | null>(null);

export function UserProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<string>(currentUser());
  const qc = useQueryClient();
  useEffect(() => {
    try {
      localStorage.setItem("corvo.user", user);
    } catch {
      /* private mode */
    }
  }, [user]);
  const setUser = (name: string) => {
    setUserState(name);
    try {
      localStorage.setItem("corvo.user", name);
    } catch {
      /* ignore */
    }
    qc.invalidateQueries();
  };
  return <UserCtx.Provider value={{ user, role: ROLE_OF[user] ?? "BUYER", setUser }}>{children}</UserCtx.Provider>;
}

export function useUser(): Ctx {
  const ctx = useContext(UserCtx);
  if (!ctx) throw new Error("useUser outside provider");
  return ctx;
}
