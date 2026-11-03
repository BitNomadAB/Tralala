import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RepositoryTokenGuide } from "@/features/settings/RepositoryTokenGuide";
import { repositorySlug } from "@/lib/repositorySlug";

describe("repositorySlug", () => {
  it("takes owner and repository from a GitHub URL", () => {
    expect(repositorySlug("https://github.com/acme/rocket")).toBe("acme/rocket");
    expect(repositorySlug(" https://github.com/acme/rocket/ ")).toBe("acme/rocket");
    expect(repositorySlug("https://github.com/acme/rocket.git")).toBe("acme/rocket");
  });

  it("falls back to a neutral placeholder while the field is empty or invalid", () => {
    expect(repositorySlug("")).toBe("your-org/your-repo");
    expect(repositorySlug("github.com/acme/rocket")).toBe("your-org/your-repo");
    expect(repositorySlug("https://github.com/acme")).toBe("your-org/your-repo");
  });

  it("carries no example repository of its own", () => {
    expect(repositorySlug("")).not.toMatch(/tralala|bitnomad/i);
  });
});

describe("RepositoryTokenGuide", () => {
  it("names the repository from the URL field and links the token page", () => {
    render(<RepositoryTokenGuide url="https://github.com/acme/rocket" />);
    expect(screen.getByText("How do I create the key?")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "github.com/settings/personal-access-tokens/new" }),
    ).toHaveAttribute("href", "https://github.com/settings/personal-access-tokens/new");
    expect(screen.getAllByText(/acme\/rocket/).length).toBeGreaterThan(0);
  });

  it("shows placeholders instead of a foreign repository before a URL is typed", () => {
    render(<RepositoryTokenGuide url="" />);
    expect(screen.getByText(/fill in the URL field above/)).toBeInTheDocument();
    expect(screen.getAllByText(/your-org\/your-repo/).length).toBeGreaterThan(0);
  });

  it("states that a deploy key is not what this field reads", () => {
    render(<RepositoryTokenGuide url="https://github.com/acme/rocket" />);
    expect(screen.getByText(/Tralala never uses SSH or a git binary/)).toBeInTheDocument();
    expect(screen.getAllByText(/Contents/).length).toBeGreaterThan(0);
  });

  it("explains the organisation-wide token for an organisation profile", () => {
    render(<RepositoryTokenGuide url="https://github.com/acme/rocket" />);
    expect(screen.getByText(/One key for several repositories/)).toBeInTheDocument();
    expect(screen.getByText(/All repositories/)).toBeInTheDocument();
  });
});
