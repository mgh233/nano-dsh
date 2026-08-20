# Cap production code for end-to-end readability

nano-dsh targets at most 1,000 non-empty, non-comment Python lines under
`nano_dsh/`, with no production file over 200 lines. Tests, documentation, and TOML
configuration do not count toward this limit. Feature breadth must yield when
it would prevent a new reader from understanding the whole implementation.
