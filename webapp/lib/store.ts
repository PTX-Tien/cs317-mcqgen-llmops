import { create } from "zustand"
import { User } from "@/types"

interface AuthStore {
  user: User | null
  token: string | null
  setAuth: (user: User, token: string) => void
  clearAuth: () => void
  isAdmin: () => boolean
}

export const useAuthStore = create<AuthStore>((set, get) => ({
  user: null,
  token: null,
  setAuth: (user, token) => {
    localStorage.setItem("access_token", token)
    set({ user, token })
  },
  clearAuth: () => {
    localStorage.removeItem("access_token")
    localStorage.removeItem("refresh_token")
    set({ user: null, token: null })
  },
  isAdmin: () => get().user?.role === "admin",
}))
