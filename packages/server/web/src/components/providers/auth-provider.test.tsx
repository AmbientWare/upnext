import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { AuthProvider } from "./auth-provider";
import { useAuth } from "./use-auth";

function AuthConsumer() {
  const { authToken, isAuthenticated, login, logout } = useAuth();
  return (
    <div>
      <div data-testid="auth-token">{authToken ?? ""}</div>
      <div data-testid="is-authenticated">{String(isAuthenticated)}</div>
      <button onClick={() => login("key-123")}>login</button>
      <button onClick={() => logout()}>logout</button>
    </div>
  );
}

describe("AuthProvider", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("throws when useAuth is used outside the provider", () => {
    expect(() => render(<AuthConsumer />)).toThrow(
      "useAuth must be used within an AuthProvider"
    );
  });

  it("stores and clears the auth token", () => {
    render(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    );

    expect(screen.getByTestId("auth-token")).toHaveTextContent("");
    expect(screen.getByTestId("is-authenticated")).toHaveTextContent("false");

    fireEvent.click(screen.getByText("login"));
    expect(screen.getByTestId("auth-token")).toHaveTextContent("key-123");
    expect(screen.getByTestId("is-authenticated")).toHaveTextContent("true");

    fireEvent.click(screen.getByText("logout"));
    expect(screen.getByTestId("auth-token")).toHaveTextContent("");
    expect(screen.getByTestId("is-authenticated")).toHaveTextContent("false");
  });
});
