import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AuthProvider } from "./auth-provider";
import { useAuth } from "./use-auth";

function AuthConsumer() {
  const { apiKey, isAuthenticated, isAdmin, login, logout, setIsAdmin } = useAuth();

  return (
    <div>
      <div data-testid="api-key">{apiKey ?? ""}</div>
      <div data-testid="is-authenticated">{String(isAuthenticated)}</div>
      <div data-testid="is-admin">{String(isAdmin)}</div>
      <button type="button" onClick={() => login("key-123")}>
        login
      </button>
      <button type="button" onClick={() => setIsAdmin(true)}>
        set-admin
      </button>
      <button type="button" onClick={logout}>
        logout
      </button>
    </div>
  );
}

describe("AuthProvider", () => {
  it("throws when useAuth is used outside provider", () => {
    expect(() => render(<AuthConsumer />)).toThrow("useAuth must be used within an AuthProvider");
  });

  it("updates auth state on login and logout", async () => {
    localStorage.clear();
    const user = userEvent.setup();

    render(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    );

    expect(screen.getByTestId("is-authenticated")).toHaveTextContent("false");
    expect(screen.getByTestId("is-admin")).toHaveTextContent("false");

    await user.click(screen.getByRole("button", { name: "login" }));
    await user.click(screen.getByRole("button", { name: "set-admin" }));

    expect(screen.getByTestId("api-key")).toHaveTextContent("key-123");
    expect(screen.getByTestId("is-authenticated")).toHaveTextContent("true");
    expect(screen.getByTestId("is-admin")).toHaveTextContent("true");

    await user.click(screen.getByRole("button", { name: "logout" }));

    expect(screen.getByTestId("api-key")).toHaveTextContent("");
    expect(screen.getByTestId("is-authenticated")).toHaveTextContent("false");
    expect(screen.getByTestId("is-admin")).toHaveTextContent("false");
  });
});
