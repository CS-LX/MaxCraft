// Original Minecraft atlas/UVs and per-vertex tint, shared across mesh batches.
float4x4 WorldViewProjection : WorldViewProjection < string UIWidget="None"; >;
Texture2D Sprite : DiffuseMap <
    string UIName="Minecraft atlas"; string ResourceType="2D";
    int Texcoord=0; int MapChannel=1;
>;
int TintChannel : Texcoord < int Texcoord=1; int MapChannel=0; string UIWidget="None"; >;
SamplerState Pixels { Filter=MIN_MAG_MIP_POINT; AddressU=Wrap; AddressV=Wrap; };
struct VIn { float4 position:POSITION; float2 uv:TEXCOORD0; float3 tint:TEXCOORD1; };
struct VOut { float4 position:SV_Position; float2 uv:TEXCOORD0; float3 tint:TEXCOORD1; };
VOut VS(VIn v) {
    VOut o; o.position=mul(v.position,WorldViewProjection); o.uv=v.uv; o.tint=v.tint; return o;
}
float4 PS(VOut v):SV_Target {
    float4 t=Sprite.Sample(Pixels,v.uv);
    clip(t.a-0.5);
    return float4(t.rgb*v.tint,1);
}
DepthStencilState WriteDepth {
    DepthEnable=true; DepthWriteMask=ALL; DepthFunc=LESS_EQUAL; StencilEnable=false;
};
RasterizerState FrontFaces { CullMode=BACK; FrontCounterClockwise=false; FillMode=SOLID; DepthClipEnable=true; };
BlendState Opaque { BlendEnable[0]=false; RenderTargetWriteMask[0]=15; };
technique11 Cutout {
    pass P0 {
        SetDepthStencilState(WriteDepth,0);
        SetRasterizerState(FrontFaces);
        SetBlendState(Opaque,float4(0,0,0,0),0xffffffff);
        SetVertexShader(CompileShader(vs_5_0,VS())); SetGeometryShader(NULL);
        SetPixelShader(CompileShader(ps_5_0,PS()));
    }
}

